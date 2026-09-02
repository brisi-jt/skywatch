"""Measure the classifier against listener feedback.

Listener votes are the closest thing the station has to ground truth: if a
clip has more thumbs-up than thumbs-down, a listener thought it was worth
hearing. Comparing that with the classifier's latest verdict gives a
precision/recall read and, more usefully, the list of clips where the two
disagree — the raw material for growing the eval set.
"""

from dataclasses import dataclass

from sqlalchemy import func
from sqlmodel import Session, select

from skywatch.api.schemas import EvalDisagreement, EvalFeedbackResponse, Link
from skywatch.db.enums import FeedbackVerdict
from skywatch.db.models import Classification, Feedback, Recording, Transcript

SNIPPET_LENGTH = 140


def human_interesting(up: int, down: int) -> bool:
    """A clip is worth hearing to listeners when up-votes outnumber down-votes."""
    return up > down


@dataclass(frozen=True)
class ClipVerdict:
    """One clip's classifier verdict versus its listener verdict."""

    recording: Recording
    classification: Classification
    up: int
    down: int
    transcript_snippet: str | None

    @property
    def human_interesting(self) -> bool:
        return human_interesting(self.up, self.down)


def _feedback_counts(session: Session) -> dict[int, dict[str, int]]:
    counts: dict[int, dict[str, int]] = {}
    rows = session.exec(
        select(Feedback.recording_id, Feedback.verdict, func.count()).group_by(
            Feedback.recording_id, Feedback.verdict
        )
    ).all()
    for rec_id, verdict, count in rows:
        counts.setdefault(rec_id, {"up": 0, "down": 0})[FeedbackVerdict(verdict).value] = count
    return counts


def _latest_classification(session: Session, recording_id: int) -> Classification | None:
    return session.exec(
        select(Classification)
        .where(Classification.recording_id == recording_id)
        .order_by(Classification.id.desc())  # type: ignore[union-attr]
    ).first()


def _latest_transcript_text(session: Session, recording_id: int) -> str | None:
    row = session.exec(
        select(Transcript.text)
        .where(Transcript.recording_id == recording_id)
        .order_by(Transcript.id.desc())  # type: ignore[union-attr]
    ).first()
    return row


def collect_verdicts(session: Session) -> list[ClipVerdict]:
    """Every clip that has both a listener vote and a classification."""
    counts = _feedback_counts(session)
    verdicts: list[ClipVerdict] = []
    for rec_id, tally in counts.items():
        recording = session.get(Recording, rec_id)
        classification = _latest_classification(session, rec_id)
        if recording is None or classification is None:
            continue
        snippet = _latest_transcript_text(session, rec_id)
        verdicts.append(
            ClipVerdict(
                recording=recording,
                classification=classification,
                up=tally["up"],
                down=tally["down"],
                transcript_snippet=snippet[:SNIPPET_LENGTH] if snippet else None,
            )
        )
    verdicts.sort(key=lambda v: v.recording.id, reverse=True)
    return verdicts


def compute_feedback_eval(session: Session) -> EvalFeedbackResponse:
    verdicts = collect_verdicts(session)
    tp = fp = fn = tn = 0
    disagreements: list[EvalDisagreement] = []
    for v in verdicts:
        predicted = v.classification.is_interesting
        actual = v.human_interesting
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1
        if predicted != actual:
            disagreements.append(
                EvalDisagreement(
                    recording_id=v.recording.id,
                    classified_interesting=predicted,
                    category=v.classification.category,
                    human_interesting=actual,
                    feedback_up=v.up,
                    feedback_down=v.down,
                    transcript_snippet=v.transcript_snippet,
                    links={"recording": Link(href=f"/recordings/{v.recording.id}")},
                )
            )
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return EvalFeedbackResponse(
        sample_size=len(verdicts),
        precision=round(precision, 4) if precision is not None else None,
        recall=round(recall, 4) if recall is not None else None,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_negatives=tn,
        disagreements=disagreements,
        links={"self": Link(href="/eval/feedback")},
    )
