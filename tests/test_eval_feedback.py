"""Feedback eval: precision/recall + disagreements, the endpoint, and helper."""

from fastapi.testclient import TestClient

from skywatch.api.services.eval_feedback import collect_verdicts, human_interesting
from skywatch.db.enums import FeedbackVerdict


def _clip(seed, freq, *, classifier_interesting: bool, up: int, down: int):
    rec = seed.recording(freq)
    seed.classification(rec, is_interesting=classifier_interesting)
    for _ in range(up):
        seed.feedback(rec, verdict=FeedbackVerdict.UP)
    for _ in range(down):
        seed.feedback(rec, verdict=FeedbackVerdict.DOWN)
    return rec


def test_human_interesting_rule():
    assert human_interesting(2, 0)
    assert not human_interesting(0, 1)
    assert not human_interesting(1, 1)  # ties do not count as interesting


class TestComputeFeedbackEval:
    def _compute(self, session):
        from skywatch.api.services.eval_feedback import compute_feedback_eval

        return compute_feedback_eval(session)

    def test_precision_recall_and_disagreements(self, session, seed):
        freq = seed.frequency()
        _clip(seed, freq, classifier_interesting=True, up=2, down=0)  # TP
        fp = _clip(seed, freq, classifier_interesting=True, up=0, down=2)  # FP
        fn = _clip(seed, freq, classifier_interesting=False, up=2, down=0)  # FN
        _clip(seed, freq, classifier_interesting=False, up=0, down=1)  # TN
        # no feedback -> excluded
        seed.classification(seed.recording(freq), is_interesting=True)

        result = self._compute(session)
        assert result.sample_size == 4
        assert result.true_positives == 1
        assert result.false_positives == 1
        assert result.false_negatives == 1
        assert result.true_negatives == 1
        assert result.precision == 0.5
        assert result.recall == 0.5
        ids = {d.recording_id for d in result.disagreements}
        assert ids == {fp.id, fn.id}

    def test_precision_recall_null_when_nothing_to_divide(self, session, seed):
        # Only a true negative: no positives predicted, none actual.
        _clip(seed, seed.frequency(), classifier_interesting=False, up=0, down=1)
        result = self._compute(session)
        assert result.precision is None
        assert result.recall is None
        assert result.sample_size == 1

    def test_disagreements_carry_snippet_and_counts(self, session, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)
        seed.transcript(rec, text="cleared to land runway two two")
        seed.classification(rec, is_interesting=False)
        seed.feedback(rec, verdict=FeedbackVerdict.UP)
        result = self._compute(session)
        (dis,) = result.disagreements
        assert dis.human_interesting is True
        assert dis.classified_interesting is False
        assert dis.feedback_up == 1
        assert dis.transcript_snippet == "cleared to land runway two two"


def test_endpoint(client: TestClient, seed):
    _clip(seed, seed.frequency(), classifier_interesting=True, up=0, down=2)
    body = client.get("/eval/feedback").json()
    assert body["sample_size"] == 1
    assert body["false_positives"] == 1
    assert len(body["disagreements"]) == 1
    assert body["_links"]["self"]["href"] == "/eval/feedback"


def test_collect_verdicts_excludes_unclassified_and_unvoted(session, seed):
    freq = seed.frequency()
    # feedback but no classification -> excluded
    voted_only = seed.recording(freq)
    seed.feedback(voted_only, verdict=FeedbackVerdict.UP)
    # classification but no feedback -> excluded
    classified_only = seed.recording(freq)
    seed.classification(classified_only, is_interesting=True)
    assert collect_verdicts(session) == []
