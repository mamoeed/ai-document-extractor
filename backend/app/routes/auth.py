import logging

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import create_access_token, verify_credentials
from ..config import AppSettings, get_settings
from ..schemas import LoginRequest, LoginResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, settings: AppSettings = Depends(get_settings)) -> LoginResponse:
    if not verify_credentials(body.username, body.password, settings):
        log.warning("Failed login for username %r", body.username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    log.info("User %s logged in", body.username)
    return LoginResponse(
        access_token=create_access_token(body.username, settings),
        username=body.username,
        expires_in_minutes=settings.jwt_expire_minutes,
    )
