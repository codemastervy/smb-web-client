"""Transfers, preferences, and auth."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import auth
from ..models import LoginRequest, Preferences
from ..services import transfers
from ..services.store import prefs_store

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
transfers_router = APIRouter(prefix="/api/transfers", tags=["transfers"],
                             dependencies=[Depends(auth.require_auth)])
prefs_router = APIRouter(prefix="/api/preferences", tags=["preferences"],
                         dependencies=[Depends(auth.require_auth)])


@auth_router.get("/status")
async def status(request: Request) -> dict:
    token = request.cookies.get(auth.COOKIE_NAME)
    return {
        "authRequired": auth.auth_required(),
        "configured": auth.auth_configured(),
        "authenticated": (not auth.auth_required()) or auth.session_valid(token),
    }


@auth_router.post("/login")
async def login(req: LoginRequest, request: Request,
                response: Response) -> dict:
    if not auth.auth_required():
        return {"authenticated": True, "note": "authentication is disabled"}

    client = request.client.host if request.client else "unknown"
    if auth.throttled(client):
        raise HTTPException(status_code=429,
                            detail="too many failed attempts, try again shortly")
    if not auth.verify_password(req.password):
        auth.record_failure(client)
        raise HTTPException(status_code=401, detail="incorrect password")

    auth.clear_failures(client)
    auth.issue_session(response, secure=request.url.scheme == "https")
    return {"authenticated": True}


@auth_router.post("/logout")
async def logout(response: Response) -> dict:
    auth.clear_session(response)
    return {"authenticated": False}


@transfers_router.get("")
async def list_transfers() -> dict:
    return {"transfers": transfers.listing()}


@transfers_router.post("/clear")
async def clear_transfers() -> dict:
    return {"cleared": transfers.clear_finished()}


@prefs_router.get("")
async def get_preferences() -> dict:
    return Preferences(**prefs_store.read()).model_dump(by_alias=True)


@prefs_router.put("")
async def set_preferences(prefs: Preferences) -> dict:
    prefs_store.write(prefs.model_dump())
    return prefs.model_dump(by_alias=True)
