"""The shipped runbook and glossary: served by the API, and structurally sound.

These tests run against the real ``content/`` documents, not fixture
markdown — they are the guarantee that a fresh checkout serves useful docs.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = REPO_ROOT / "content"

RUNBOOK = CONTENT_DIR / "RUNBOOK.md"
GLOSSARY = CONTENT_DIR / "GLOSSARY.md"
EXTENSIONS = REPO_ROOT / "EXTENSIONS.md"


@pytest.fixture()
def real_content_client(engine, tmp_path, monkeypatch):
    """An API client whose content dir is the real repo content/ directory."""
    from fastapi.testclient import TestClient

    from skywatch.api.app import create_app
    from skywatch.settings import Settings

    monkeypatch.setenv("SKYWATCH_CONFIG", str(tmp_path / "no-config.yaml"))
    settings = Settings(data_root=tmp_path / "data", _env_file=None)
    app = create_app(settings, engine=engine, content_dir=CONTENT_DIR)
    with TestClient(app) as c:
        yield c


def headings(markdown: str, level: str = "## ") -> list[str]:
    return [
        line.removeprefix(level).strip() for line in markdown.splitlines() if line.startswith(level)
    ]


class TestServedDocuments:
    def test_runbook_served_with_real_content(self, real_content_client):
        response = real_content_client.get("/runbook")

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "runbook"
        assert body["markdown"] == RUNBOOK.read_text()
        assert body["_links"]["self"]["href"] == "/runbook"

    def test_glossary_served_with_real_content(self, real_content_client):
        response = real_content_client.get("/glossary")

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "glossary"
        assert body["markdown"] == GLOSSARY.read_text()


class TestRunbookStructure:
    def test_has_sectioned_headings_for_toc(self):
        sections = headings(RUNBOOK.read_text())
        assert len(sections) >= 8, "runbook should be sectioned with ## headings"

    def test_covers_the_operating_essentials(self):
        text = RUNBOOK.read_text().lower()
        for topic in (
            "antenna",
            "gain",
            "squelch",
            "backup",
            "dongle",
            "frequenc",
            "disk",
            "launchctl",
        ):
            assert topic in text, f"runbook is missing coverage of: {topic}"

    def test_carries_the_uk_legal_disclaimer(self):
        text = RUNBOOK.read_text()
        assert "Wireless Telegraphy Act" in text
        assert "rebroadcast" in text.lower()


class TestGlossaryStructure:
    def test_one_heading_per_term_alphabetical(self):
        terms = headings(GLOSSARY.read_text())
        assert len(terms) >= 15
        assert terms == sorted(terms, key=str.lower), "glossary terms must be alphabetical"

    def test_required_terms_present(self):
        text = GLOSSARY.read_text().lower()
        for term in (
            "squawk",
            "atis",
            "tower",
            "ground",
            "approach",
            "radar",
            "readback",
            "qnh",
            "flight level",
            "hold",
            "guard",
            "ads-b",
            "callsign",
            "squelch",
            "gain",
            # vocabulary the classification reasons can surface
            "mayday",
            "pan-pan",
            "tcas",
            "go-around",
        ):
            assert term in text, f"glossary is missing: {term}"


class TestProseHygiene:
    """The documents are the product: no process leftovers in any of them."""

    @pytest.mark.parametrize("path", [RUNBOOK, GLOSSARY, EXTENSIONS])
    def test_no_ticket_ids_or_process_meta(self, path):
        text = path.read_text()
        assert not re.search(r"\b(ENG|SKW|SUM|SRE)-\d+", text)
        assert "this PR" not in text
        assert "TODO" not in text
