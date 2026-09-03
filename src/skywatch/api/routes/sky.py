"""The /sky route: live positions overhead, fused with what the station heard."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from skywatch.api.deps import get_session, get_settings, get_sky_service
from skywatch.api.schemas import SkyResponse
from skywatch.api.services.sky import SkyService, build_sky_response
from skywatch.settings import Settings

router = APIRouter(tags=["sky"])


@router.get(
    "/sky",
    response_model=SkyResponse,
    summary="What's overhead right now",
    description=(
        "Live aircraft positions within the station's configured radius, tried "
        "against a chain of community ADS-B aggregators and falling back to "
        "OpenSky when all of them are unavailable. Each aircraft is marked "
        "`heard_recently` when its hex matches a clip captured within the "
        "station's heard window, linking the live picture to actual radio "
        "traffic. Responses are cached for a few seconds so multiple open "
        "dashboard tabs share one upstream lookup. When every source in the "
        "chain is down this still returns 200 with `source` null and an "
        "empty aircraft list — a quiet sky and a down source chain look the "
        "same on the wire except for that field."
    ),
)
def get_sky(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    sky_service: Annotated[SkyService, Depends(get_sky_service)],
) -> SkyResponse:
    return build_sky_response(session, sky_service, settings=settings)
