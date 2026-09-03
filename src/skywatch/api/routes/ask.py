"""The /ask route: a plain-English question, answered from the station's own clips."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from skywatch.api.deps import get_classifier_chain, get_fts_available, get_session, get_settings
from skywatch.api.errors import ProblemDetail
from skywatch.api.schemas import AskRequest, AskResponse
from skywatch.api.services.ask import answer_question
from skywatch.providers.llm.base import Classifier
from skywatch.settings import Settings

router = APIRouter(tags=["ask"])


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask the station a question",
    description=(
        "Answers a plain-English question about what the station has heard. "
        "The most relevant recorded clips are found by searching their "
        "transcripts and handed to the same model chain used for daily "
        "narratives and classification, so the answer is grounded in what "
        "was actually recorded rather than general knowledge; `sources` "
        "lists the clips it drew on, best match first, and is empty when "
        "nothing relevant has been recorded. Counted against the station's "
        "daily model budget and rate-limited to one question at a time. "
        "Returns 429 `ask_rate_limited` if asked again too soon, and 503 "
        "`ask_unavailable` when no classifier is configured or the budget "
        "is used up."
    ),
    responses={
        429: {"model": ProblemDetail, "description": "Asked again too soon."},
        503: {"model": ProblemDetail, "description": "No classifier available to answer."},
    },
)
def ask(
    body: AskRequest,
    session: Annotated[Session, Depends(get_session)],
    chain: Annotated[list[Classifier], Depends(get_classifier_chain)],
    fts_available: Annotated[bool, Depends(get_fts_available)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AskResponse:
    return answer_question(
        session,
        question=body.question,
        chain=chain,
        daily_call_cap=settings.llm.daily_call_cap,
        fts_available=fts_available,
    )
