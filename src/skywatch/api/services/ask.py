"""Ask the station: a natural-language question answered from its own clips.

The same classifier provider chain and daily budget the pipeline already
uses for classification and the daily narrative answers questions too.
Retrieval finds the clips most likely to be relevant by searching their
transcripts — FTS5 when the database has it, a plain scan otherwise — caps
how many are ever handed to the model, and the prompt tells the model to
answer only from what it is given.
"""

import re
from datetime import UTC, datetime

from sqlalchemy import or_
from sqlalchemy import text as sa_text
from sqlmodel import Session, select
from starlette import status

from skywatch.api.errors import APIErrorCode, ProblemException
from skywatch.api.schemas import AskResponse, AskSource
from skywatch.db.models import Frequency, Recording, Setting, Transcript
from skywatch.pipeline import budget
from skywatch.providers.llm.base import Classifier, ClassifierError
from skywatch.providers.llm.prompt import ASK_SYSTEM_PROMPT, build_ask_prompt

MAX_CONTEXT_CLIPS = 8
"""How many retrieved clips are ever handed to the model as context."""

SNIPPET_LENGTH = 200

MIN_ASK_INTERVAL_S = 15
"""A short cooldown between questions. This is independent of — and much
shorter than — the daily model budget; it guards against a mis-clicked
double submit rather than gatekeeping normal use."""

LAST_ASKED_KEY = "ask:last_asked_at"
"""Settings-table key holding the UTC timestamp of the last accepted question."""

_MIN_KEYWORD_LENGTH = 3
_MAX_KEYWORDS = 8
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "did",
        "does",
        "do",
        "done",
        "when",
        "what",
        "which",
        "who",
        "where",
        "how",
        "many",
        "much",
        "on",
        "in",
        "at",
        "to",
        "for",
        "of",
        "and",
        "or",
        "that",
        "this",
        "these",
        "those",
        "it",
        "has",
        "have",
        "had",
        "any",
        "with",
        "about",
        "there",
        "been",
        "being",
        "you",
        "your",
        "can",
        "will",
        "would",
        "should",
        "just",
        "please",
    }
)


def _keywords(question: str) -> list[str]:
    """Distinct, meaningful words from a question, in order, capped in count."""
    found: list[str] = []
    for word in _WORD_RE.findall(question.lower()):
        if len(word) < _MIN_KEYWORD_LENGTH or word in _STOPWORDS:
            continue
        if word not in found:
            found.append(word)
        if len(found) >= _MAX_KEYWORDS:
            break
    return found


def _retrieve(
    session: Session,
    question: str,
    *,
    fts_available: bool,
    limit: int = MAX_CONTEXT_CLIPS,
) -> list[Recording]:
    """The clips most likely to answer the question, best match first.

    Every keyword is OR-ed together — a natural-language question rarely has
    every one of its words in a single transcript, so this favours recall
    over the AND-everything grammar the clip-search box uses.
    """
    keywords = _keywords(question)
    if not keywords:
        return []

    if fts_available:
        # bm25 can only be read when the FTS table is the one being iterated
        # (see db/fts.py), so match it alone and map transcript rowids back
        # to recordings here, exactly as the clip-search route does.
        match = " OR ".join(f'"{word}"' for word in keywords)
        rows = session.execute(
            sa_text(
                "SELECT rowid AS tid, bm25(transcripts_fts) AS rank FROM transcripts_fts "
                "WHERE transcripts_fts MATCH :match ORDER BY rank LIMIT :limit"
            ).bindparams(match=match, limit=limit)
        ).all()
        transcript_ids = [row[0] for row in rows]
        if not transcript_ids:
            return []
        recording_by_transcript = dict(
            session.execute(
                select(Transcript.id, Transcript.recording_id).where(
                    Transcript.id.in_(transcript_ids)  # type: ignore[attr-defined]
                )
            ).all()
        )
        ordered_ids: list[int] = []
        seen: set[int] = set()
        for transcript_id in transcript_ids:
            recording_id = recording_by_transcript.get(transcript_id)
            if recording_id is not None and recording_id not in seen:
                seen.add(recording_id)
                ordered_ids.append(recording_id)
        by_id = {
            rec.id: rec
            for rec in session.exec(
                select(Recording).where(Recording.id.in_(ordered_ids))  # type: ignore[attr-defined]
            ).all()
        }
        return [by_id[rid] for rid in ordered_ids if rid in by_id]

    conditions = [Transcript.text.ilike(f"%{word}%") for word in keywords]  # type: ignore[union-attr]
    stmt = (
        select(Recording)
        .join(Transcript, Transcript.recording_id == Recording.id)
        .where(or_(*conditions))
        .order_by(
            Recording.started_at_utc.desc(),  # type: ignore[attr-defined]
            Recording.id.desc(),  # type: ignore[union-attr]
        )
        .distinct()
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def _sources(session: Session, recordings: list[Recording]) -> list[AskSource]:
    if not recordings:
        return []
    freq_labels = {
        f.id: f.label
        for f in session.exec(
            select(Frequency).where(
                Frequency.id.in_({rec.freq_id for rec in recordings})  # type: ignore[attr-defined]
            )
        ).all()
    }
    sources: list[AskSource] = []
    for rec in recordings:
        text = session.exec(
            select(Transcript.text)
            .where(Transcript.recording_id == rec.id)
            .order_by(Transcript.id.desc())  # type: ignore[union-attr]
        ).first()
        sources.append(
            AskSource(
                recording_id=rec.id,
                frequency_label=freq_labels.get(rec.freq_id, "an unknown frequency"),
                started_at_utc=rec.started_at_utc,
                transcript_snippet=(text or "")[:SNIPPET_LENGTH].strip(),
            )
        )
    return sources


def _clip_lines(sources: list[AskSource]) -> list[str]:
    return [
        f"{src.started_at_utc:%Y-%m-%d %H:%M} UTC on {src.frequency_label}: "
        f'"{src.transcript_snippet}"'
        for src in sources
    ]


def _last_asked_at(session: Session) -> datetime | None:
    row = session.get(Setting, LAST_ASKED_KEY)
    if row is None:
        return None
    try:
        return datetime.fromisoformat(row.value)
    except ValueError:
        return None


def _remember_asked(session: Session, now: datetime) -> None:
    value = now.astimezone(UTC).isoformat()
    row = session.get(Setting, LAST_ASKED_KEY)
    if row is None:
        session.add(Setting(key=LAST_ASKED_KEY, value=value))
    else:
        row.value = value
        session.add(row)
    session.commit()


def _meter_call(session: Session, provider, day) -> None:
    """Meter one real model call in its own committed transaction.

    A separate session on the same engine, mirroring the daily narrative: the
    HTTP call is spent whether or not the caller's transaction later commits,
    so the budget must record it independently.
    """
    with Session(session.get_bind()) as budget_session:
        budget.record_call(budget_session, provider, day)
        budget_session.commit()


def _run_chain(
    session: Session,
    chain: list[Classifier],
    daily_call_cap: int,
    user_prompt: str,
    *,
    day,
) -> str | None:
    """Try each provider in turn; return the first answer, budget permitting."""
    for classifier in chain:
        narrate = getattr(classifier, "narrate", None)
        if narrate is None:
            continue
        if budget.remaining(session, classifier.provider, day, daily_call_cap) <= 0:
            continue
        _meter_call(session, classifier.provider, day)
        try:
            text = narrate(ASK_SYSTEM_PROMPT, user_prompt)
        except ClassifierError:
            continue
        cleaned = text.strip()
        if cleaned:
            return cleaned
    return None


def answer_question(
    session: Session,
    *,
    question: str,
    chain: list[Classifier],
    daily_call_cap: int,
    fts_available: bool,
    now: datetime | None = None,
) -> AskResponse:
    """Answer a question from the station's own recorded clips.

    Raises 429 ``ask_rate_limited`` when asked again inside the cooldown, and
    503 ``ask_unavailable`` when no classifier is configured or every
    provider's daily budget is used up. A question that matches nothing
    still reaches the model — it is told plainly that no clips matched, so
    it can say so rather than guessing.
    """
    stripped = question.strip()
    if not stripped:
        raise ProblemException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            APIErrorCode.VALIDATION_ERROR,
            "a question is required",
        )

    now = now or datetime.now(UTC)
    last_asked = _last_asked_at(session)
    if last_asked is not None:
        age = (now - last_asked).total_seconds()
        if age < MIN_ASK_INTERVAL_S:
            raise ProblemException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                APIErrorCode.ASK_RATE_LIMITED,
                "asked again too soon; wait a moment before asking another question",
                extensions={"retry_after_s": int(MIN_ASK_INTERVAL_S - age)},
            )
    _remember_asked(session, now)

    if not chain:
        raise ProblemException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            APIErrorCode.ASK_UNAVAILABLE,
            "no classifier is configured to answer questions",
        )

    recordings = _retrieve(session, stripped, fts_available=fts_available)
    sources = _sources(session, recordings)
    user_prompt = build_ask_prompt(question=stripped, clips=_clip_lines(sources))
    answer = _run_chain(session, chain, daily_call_cap, user_prompt, day=now.date())
    if answer is None:
        raise ProblemException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            APIErrorCode.ASK_UNAVAILABLE,
            "the station could not answer right now; the model budget may be "
            "used up until it resets",
        )
    session.commit()
    return AskResponse(question=stripped, answer=answer, sources=sources)
