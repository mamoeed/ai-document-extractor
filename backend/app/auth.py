"""Single hardcoded user (APP_USERNAME / APP_PASSWORD) with a signed JWT bearer token."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import AppSettings, get_settings

ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=False)


def verify_credentials(username: str, password: str, settings: AppSettings) -> bool:
    user_ok = secrets.compare_digest(username.encode(), settings.app_username.encode())
    pass_ok = secrets.compare_digest(password.encode(), settings.app_password.get_secret_value().encode())
    return user_ok and pass_ok


def create_access_token(username: str, settings: AppSettings) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": username, "iat": now, "exp": now + timedelta(minutes=settings.jwt_expire_minutes)}
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: AppSettings = Depends(get_settings),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret.get_secret_value(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Session expired - please log in again") from None
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid token - please log in again") from None
    username = payload.get("sub")
    if not username:
        raise _unauthorized("Invalid token - please log in again")
    return str(username)
