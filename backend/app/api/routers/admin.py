from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.models.location import Location
from app.models.post import Post
from app.repositories.channel_state_repository import ChannelStateRepository
from app.repositories.post_repository import PostRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_JWT_ALGORITHM = "HS256"
_TOKEN_TTL_HOURS = 24
_bearer = HTTPBearer()


def _verify_admin(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> None:
    """Validate the Bearer JWT token issued by POST /api/admin/auth/token."""
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[_JWT_ALGORITHM],
        )
        if payload.get("sub") != "admin":
            raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


AdminDep = Annotated[None, Depends(_verify_admin)]


def _serialize_location(loc: Location) -> dict:
    return {
        "id": loc.id,
        "address": loc.address,
        "street_name": loc.street_name,
        "geo_type": loc.geo_type,
        "confidence": loc.confidence,
        "out_of_bounds": loc.out_of_bounds,
        "resolved": loc.resolved,
        "resolved_by": loc.resolved_by,
    }


def _serialize_post(post: Post) -> dict:
    return {
        "id": post.id,
        "telegram_id": post.telegram_id,
        "channel_id": post.channel_id,
        "raw_text": post.raw_text,
        "cleaned_text": post.cleaned_text,
        "post_date": post.post_date.isoformat() if post.post_date else None,
        "fetched_at": post.fetched_at.isoformat() if post.fetched_at else None,
        "status": post.status,
        "error_message": post.error_message,
        "locations": [_serialize_location(loc) for loc in post.locations],
    }


class _LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/token")
async def login(body: _LoginRequest) -> dict:
    """Issue a JWT token for admin access.

    Returns {"access_token": "<jwt>", "token_type": "bearer"}.
    """
    if body.username != settings.admin_username or body.password != settings.admin_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = jwt.encode(
        {"sub": "admin", "exp": datetime.now(UTC) + timedelta(hours=_TOKEN_TTL_HOURS)},
        settings.jwt_secret,
        algorithm=_JWT_ALGORITHM,
    )
    return {"access_token": token, "token_type": "bearer"}


@router.get("/posts/deleted")
async def get_deleted_posts(
    session: SessionDep,
    _: AdminDep,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Return paginated list of posts deleted from Telegram.

    These posts are hidden from the public map (is_deleted=True) but preserved
    in the DB. The response includes raw_text and cleaned_text so that the admin
    can manually validate complex address extractions and understand what
    information was lost when the post was deleted.

    Response shape:
        {
            "total": <int>,
            "page": <int>,
            "limit": <int>,
            "items": [
                {
                    "id", "telegram_id", "channel_id",
                    "raw_text", "cleaned_text",
                    "post_date", "fetched_at", "status", "error_message",
                    "locations": [{ "id", "address", "street_name", "geo_type",
                                    "confidence", "out_of_bounds", "resolved",
                                    "resolved_by" }]
                },
                ...
            ]
        }
    """
    channel_repo = ChannelStateRepository(session)
    channel = await channel_repo.get_active_channel()
    if channel is None:
        raise HTTPException(status_code=404, detail="No active channel configured")

    post_repo = PostRepository(session)
    posts, total = await post_repo.get_deleted_posts(
        channel_id=channel.channel_id,
        page=page,
        limit=limit,
    )

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [_serialize_post(p) for p in posts],
    }
