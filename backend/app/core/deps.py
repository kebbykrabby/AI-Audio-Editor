import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.database import get_db
from app.models.user import User


def _unauth(code: str = "UNAUTHENTICATED", message: str = "Authentication required") -> HTTPException:
    return HTTPException(status_code=401, detail={"code": code, "message": message})


def _extract_bearer(request: Request) -> str:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header:
        raise _unauth()
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauth("INVALID_TOKEN", "Malformed authorization header")
    return token


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    token = _extract_bearer(request)
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise _unauth("TOKEN_EXPIRED", "Access token expired")
    except jwt.InvalidTokenError:
        raise _unauth("INVALID_TOKEN", "Invalid access token")

    user_id = payload.get("sub")
    if not isinstance(user_id, str):
        raise _unauth("INVALID_TOKEN", "Invalid access token")

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise _unauth("UNAUTHENTICATED", "User no longer exists")
    return user
