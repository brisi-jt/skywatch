"""Station documents: the runbook and the glossary, served as Markdown."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette import status

from skywatch.api.errors import APIErrorCode, ProblemDetail, ProblemException
from skywatch.api.schemas import DocumentResponse, Link

router = APIRouter(tags=["docs"])

_DOCUMENTS = {"runbook": "RUNBOOK.md", "glossary": "GLOSSARY.md"}


def get_content_dir(request: Request) -> Path:
    return request.app.state.content_dir


def _serve(content_dir: Path, name: str) -> DocumentResponse:
    path = content_dir / _DOCUMENTS[name]
    if not path.is_file():
        raise ProblemException(
            status.HTTP_404_NOT_FOUND,
            APIErrorCode.DOCUMENT_NOT_FOUND,
            f"the {name} is not installed on this station",
        )
    return DocumentResponse(
        name=name,
        markdown=path.read_text(),
        links={"self": Link(href=f"/{name}")},
    )


@router.get(
    "/runbook",
    response_model=DocumentResponse,
    summary="The station runbook",
    description=(
        "Operating instructions for the station — start/stop, antenna "
        "placement, tuning, troubleshooting — as raw Markdown for the client "
        "to render."
    ),
    responses={404: {"model": ProblemDetail, "description": "Runbook not installed."}},
)
def get_runbook(content_dir: Annotated[Path, Depends(get_content_dir)]) -> DocumentResponse:
    return _serve(content_dir, "runbook")


@router.get(
    "/glossary",
    response_model=DocumentResponse,
    summary="The aviation glossary",
    description=(
        "Plain-English explanations of the aviation terms that appear in "
        "transcripts and classifications, as raw Markdown for the client to "
        "render."
    ),
    responses={404: {"model": ProblemDetail, "description": "Glossary not installed."}},
)
def get_glossary(content_dir: Annotated[Path, Depends(get_content_dir)]) -> DocumentResponse:
    return _serve(content_dir, "glossary")
