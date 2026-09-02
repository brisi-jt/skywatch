"""Owner-editable watch phrases: module, prefilter, classify, and API."""

import json

from fastapi.testclient import TestClient
from sqlmodel import Session

from skywatch.db.enums import ClassificationCategory, FrequencyCategory
from skywatch.db.models import Setting
from skywatch.pipeline.prefilters import WATCH_PHRASE_PREFIX, run_prefilters
from skywatch.pipeline.watch_phrases import (
    DEFAULT_WATCH_PHRASES,
    MAX_WATCH_PHRASES,
    WATCH_PHRASES_KEY,
    clean_watch_phrases,
    load_watch_phrases,
)


class TestPrefilterWatchPhrases:
    def test_watch_phrase_flags_routine_clip(self):
        verdict = run_prefilters(
            transcript_text="report ready for the fuel bowser",
            duration_s=6.0,
            freq_category=FrequencyCategory.TOWER,
            watch_phrases=["fuel bowser"],
        )
        assert verdict.is_interesting
        assert f"{WATCH_PHRASE_PREFIX}fuel bowser" in verdict.flags
        assert verdict.category is ClassificationCategory.OTHER
        assert "fuel bowser" in verdict.reason

    def test_no_watch_phrase_no_flag(self):
        verdict = run_prefilters(
            transcript_text="cleared to land runway two two",
            duration_s=6.0,
            freq_category=FrequencyCategory.TOWER,
            watch_phrases=["fuel bowser"],
        )
        assert not verdict.is_interesting

    def test_distress_keyword_outranks_watch_phrase_category(self):
        # A watch phrase must not downgrade a genuine emergency category.
        verdict = run_prefilters(
            transcript_text="mayday mayday and also fuel bowser",
            duration_s=6.0,
            freq_category=FrequencyCategory.TOWER,
            watch_phrases=["fuel bowser"],
        )
        assert verdict.category is ClassificationCategory.EMERGENCY

    def test_matching_is_case_and_hyphen_insensitive(self):
        verdict = run_prefilters(
            transcript_text="requesting GO-AROUND now",
            duration_s=6.0,
            freq_category=FrequencyCategory.TOWER,
            watch_phrases=["go around"],
        )
        assert verdict.is_interesting


class TestLoadWatchPhrases:
    def test_defaults_when_unset(self, session: Session):
        assert load_watch_phrases(session) == DEFAULT_WATCH_PHRASES

    def test_reads_from_db(self, session: Session):
        session.add(Setting(key=WATCH_PHRASES_KEY, value=json.dumps(["go around", "diverting"])))
        session.commit()
        assert load_watch_phrases(session) == ["go around", "diverting"]

    def test_falls_back_on_invalid_json(self, session: Session):
        session.add(Setting(key=WATCH_PHRASES_KEY, value="not json"))
        session.commit()
        assert load_watch_phrases(session) == DEFAULT_WATCH_PHRASES

    def test_falls_back_when_not_a_list_of_strings(self, session: Session):
        session.add(Setting(key=WATCH_PHRASES_KEY, value=json.dumps([1, 2, 3])))
        session.commit()
        assert load_watch_phrases(session) == DEFAULT_WATCH_PHRASES


class TestCleanWatchPhrases:
    def test_trims_dedups_drops_blanks(self):
        assert clean_watch_phrases(["  mayday  ", "mayday", "", "  ", "go around"]) == [
            "mayday",
            "go around",
        ]

    def test_rejects_non_list(self):
        assert clean_watch_phrases("mayday") is None

    def test_rejects_non_string_element(self):
        assert clean_watch_phrases(["ok", 7]) is None

    def test_rejects_over_length_phrase(self):
        assert clean_watch_phrases(["x" * 101]) is None

    def test_rejects_too_many(self):
        assert clean_watch_phrases([f"phrase {i}" for i in range(MAX_WATCH_PHRASES + 1)]) is None

    def test_empty_list_is_valid(self):
        assert clean_watch_phrases([]) == []


class TestSettingsApi:
    def test_get_returns_default_watch_phrases(self, client: TestClient):
        body = client.get("/settings").json()
        assert body["watch_phrases"] == DEFAULT_WATCH_PHRASES

    def test_patch_round_trips_watch_phrases(self, client: TestClient):
        resp = client.patch(
            "/settings", json={"classify.watch_phrases": ["go around", "diverting"]}
        )
        assert resp.status_code == 200
        assert resp.json()["watch_phrases"] == ["go around", "diverting"]
        assert client.get("/settings").json()["watch_phrases"] == ["go around", "diverting"]

    def test_patch_rejects_non_list(self, client: TestClient):
        resp = client.patch("/settings", json={"classify.watch_phrases": "mayday"})
        assert resp.status_code == 422
        assert resp.json()["code"] == "invalid_setting_value"

    def test_patch_rejects_over_length(self, client: TestClient):
        resp = client.patch("/settings", json={"classify.watch_phrases": ["x" * 101]})
        assert resp.status_code == 422

    def test_patch_rejects_too_many(self, client: TestClient):
        resp = client.patch(
            "/settings",
            json={"classify.watch_phrases": [f"p{i}" for i in range(MAX_WATCH_PHRASES + 1)]},
        )
        assert resp.status_code == 422

    def test_patch_unknown_key_still_400(self, client: TestClient):
        resp = client.patch("/settings", json={"nope": "x"})
        assert resp.status_code == 400
