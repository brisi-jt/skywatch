"""Evaluation routes: how well the classifier agrees with listeners."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from skywatch.api.deps import get_session
from skywatch.api.schemas import EvalFeedbackResponse
from skywatch.api.services import eval_feedback

router = APIRouter(tags=["eval"])


@router.get(
    "/eval/feedback",
    response_model=EvalFeedbackResponse,
    summary="Classifier accuracy against listener feedback",
    description=(
        "Measures the classifier's interesting/routine verdict against listener "
        "votes as ground truth: for every clip that has both a verdict and at "
        "least one vote, a majority of thumbs-up counts as 'worth hearing'. "
        "Returns precision and recall (null until there is anything to divide) "
        "plus the full list of clips where the classifier and listeners "
        "disagreed — the clips most worth adding to the evaluation set."
    ),
)
def get_feedback_eval(
    session: Annotated[Session, Depends(get_session)],
) -> EvalFeedbackResponse:
    return eval_feedback.compute_feedback_eval(session)
