"""LiveSDRSource: conf rendering into place plus rtl_airband supervision.

Every system interaction (launchctl, rtl_test, process spawn) goes through
injected runners, so these tests never touch real hardware or launchd.
"""

from dataclasses import dataclass, field

import pytest
from sqlmodel import Session, select

from skywatch.capture.live import CommandResult, DongleNotFoundError, LiveSDRSource
from skywatch.db.enums import FrequencyCategory
from skywatch.db.models import Frequency
from skywatch.settings import CaptureSettings

RTL_TEST_FOUND = "Found 1 device(s):\n  0:  Realtek, RTL2838UHIDIR, SN: 00000001\n"
RTL_TEST_NONE = "No supported devices found.\n"


@dataclass
class FakeRunner:
    responses: dict[str, CommandResult] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, argv: list[str]) -> CommandResult:
        self.calls.append(argv)
        for prefix, result in self.responses.items():
            if " ".join(argv).startswith(prefix):
                return result
        return CommandResult(0, "", "")


class FakeProc:
    def __init__(self, argv):
        self.argv = argv
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


@pytest.fixture()
def seeded_engine(engine):
    with Session(engine) as session:
        session.add(
            Frequency(
                label="Guard 121.500",
                mhz=121.5,
                facility="Guard",
                category=FrequencyCategory.GUARD,
                tuner_group=2,
                is_active=True,
            )
        )
        session.add(
            Frequency(
                label="Stansted Tower",
                mhz=123.805,
                facility="London Stansted",
                category=FrequencyCategory.TOWER,
                tuner_group=2,
                is_active=False,
            )
        )
        session.commit()
    return engine


def make_source(engine, tmp_path, *, supervisor="subprocess", runner=None, spawn=FakeProc):
    return LiveSDRSource(
        engine,
        CaptureSettings(mode="multichannel"),
        conf_path=tmp_path / "rtl_airband.conf",
        recordings_dir=tmp_path / "recordings",
        supervisor=supervisor,
        launchd_domain="gui/501",
        runner=runner or FakeRunner({"rtl_test": CommandResult(0, "", RTL_TEST_FOUND)}),
        spawn=spawn,
    )


class TestDongleCheck:
    def test_present(self, seeded_engine, tmp_path):
        runner = FakeRunner({"rtl_test": CommandResult(0, "", RTL_TEST_FOUND)})
        source = make_source(seeded_engine, tmp_path, runner=runner)
        assert source.dongle_present() is True
        assert runner.calls[0][0] == "rtl_test"

    def test_absent(self, seeded_engine, tmp_path):
        runner = FakeRunner({"rtl_test": CommandResult(1, "", RTL_TEST_NONE)})
        source = make_source(seeded_engine, tmp_path, runner=runner)
        assert source.dongle_present() is False

    def test_start_refuses_without_a_dongle(self, seeded_engine, tmp_path):
        runner = FakeRunner({"rtl_test": CommandResult(1, "", RTL_TEST_NONE)})
        source = make_source(seeded_engine, tmp_path, runner=runner)
        with pytest.raises(DongleNotFoundError):
            source.start()


class TestConfRendering:
    def test_write_conf_renders_only_active_frequencies(self, seeded_engine, tmp_path):
        source = make_source(seeded_engine, tmp_path)
        text = source.write_conf()
        assert (tmp_path / "rtl_airband.conf").read_text() == text
        assert "121.5" in text
        assert "123.805" not in text  # inactive frequency stays out of the conf

    def test_write_conf_with_no_active_frequencies_raises(self, engine, tmp_path):
        source = make_source(engine, tmp_path)
        with pytest.raises(ValueError):
            source.write_conf()

    def test_write_conf_uses_database_tuning_values(self, seeded_engine, tmp_path):
        from skywatch.db.models import Setting

        with Session(seeded_engine) as session:
            guard = session.exec(select(Frequency).where(Frequency.is_active)).one()
            session.add(Setting(key="tuning.gain", value="38.6"))
            session.add(Setting(key="tuning.squelch_default", value="10"))
            session.add(Setting(key="tuning.ppm", value="-2"))
            session.add(Setting(key=f"tuning.squelch.{guard.id}", value="7.5"))
            session.commit()

        text = make_source(seeded_engine, tmp_path).write_conf()

        assert "gain = 38.6;" in text
        assert "correction = -2;" in text
        assert "squelch_snr_threshold = 7.5;" in text  # the per-channel override

    def test_write_conf_includes_the_stats_file_location(self, seeded_engine, tmp_path):
        source = LiveSDRSource(
            seeded_engine,
            CaptureSettings(mode="multichannel"),
            conf_path=tmp_path / "rtl_airband.conf",
            recordings_dir=tmp_path / "recordings",
            stats_filepath=tmp_path / "stats" / "rtl_airband_stats.txt",
            runner=FakeRunner({"rtl_test": CommandResult(0, "", RTL_TEST_FOUND)}),
            spawn=FakeProc,
        )
        text = source.write_conf()
        stats_path = (tmp_path / "stats" / "rtl_airband_stats.txt").as_posix()
        assert f'stats_filepath = "{stats_path}";' in text


class TestSubprocessSupervision:
    def test_start_writes_conf_then_spawns_rtl_airband_in_foreground(self, seeded_engine, tmp_path):
        spawned = []

        def spawn(argv):
            proc = FakeProc(argv)
            spawned.append(proc)
            return proc

        source = make_source(seeded_engine, tmp_path, spawn=spawn)
        source.start()

        assert (tmp_path / "rtl_airband.conf").exists()
        (proc,) = spawned
        assert proc.argv[0] == "rtl_airband"
        assert "-F" in proc.argv
        assert str(tmp_path / "rtl_airband.conf") in proc.argv
        assert source.status().running is True

        source.stop()
        assert proc.terminated
        assert source.status().running is False

    def test_status_reflects_a_died_process(self, seeded_engine, tmp_path):
        procs = []

        def spawn(argv):
            proc = FakeProc(argv)
            procs.append(proc)
            return proc

        source = make_source(seeded_engine, tmp_path, spawn=spawn)
        source.start()
        procs[0].terminated = True  # process exited underneath us
        assert source.status().running is False


class TestLaunchctlSupervision:
    def test_start_kickstarts_the_service(self, seeded_engine, tmp_path):
        runner = FakeRunner({"rtl_test": CommandResult(0, "", RTL_TEST_FOUND)})
        source = make_source(seeded_engine, tmp_path, supervisor="launchctl", runner=runner)
        source.start()

        assert (tmp_path / "rtl_airband.conf").exists()
        assert [
            "launchctl",
            "kickstart",
            "-k",
            "gui/501/com.skywatch.rtl-airband",
        ] in runner.calls

    def test_stop_kills_the_service(self, seeded_engine, tmp_path):
        runner = FakeRunner({"rtl_test": CommandResult(0, "", RTL_TEST_FOUND)})
        source = make_source(seeded_engine, tmp_path, supervisor="launchctl", runner=runner)
        source.start()
        source.stop()
        assert [
            "launchctl",
            "kill",
            "SIGTERM",
            "gui/501/com.skywatch.rtl-airband",
        ] in runner.calls

    def test_status_parses_launchctl_print(self, seeded_engine, tmp_path):
        runner = FakeRunner(
            {
                "rtl_test": CommandResult(0, "", RTL_TEST_FOUND),
                "launchctl print": CommandResult(0, "state = running\n", ""),
            }
        )
        source = make_source(seeded_engine, tmp_path, supervisor="launchctl", runner=runner)
        assert source.status().running is True

        runner.responses["launchctl print"] = CommandResult(0, "state = not running\n", "")
        assert source.status().running is False
