"""Saved connections, and connecting to them."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_auth
from ..models import ConnectRequest, ServerCreate, ServerUpdate
from ..services import servers, smb
from ..services.failures import Failure

router = APIRouter(prefix="/api/servers", tags=["servers"],
                   dependencies=[Depends(require_auth)])


def _fail(failure: Failure) -> HTTPException:
    return HTTPException(status_code=failure.http_status,
                         detail=failure.to_dict())


@router.get("")
async def list_servers() -> dict:
    profiles = servers.list_servers()
    statuses = await asyncio.to_thread(smb.all_status)
    for profile in profiles:
        profile["status"] = statuses.get(profile["id"], {"state": "idle"})
    return {"servers": profiles}


@router.post("")
async def create_server(req: ServerCreate) -> dict:
    return servers.create(req.model_dump())


@router.patch("/{server_id}")
async def update_server(server_id: str, req: ServerUpdate) -> dict:
    updated = servers.update(server_id, req.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="no such server")
    # Details changed, so any live session is stale.
    await asyncio.to_thread(smb.disconnect, server_id)
    return updated


@router.delete("/{server_id}")
async def delete_server(server_id: str) -> dict:
    await asyncio.to_thread(smb.disconnect, server_id)
    if not servers.delete(server_id):
        raise HTTPException(status_code=404, detail="no such server")
    return {"deleted": server_id}


@router.post("/{server_id}/connect")
async def connect(server_id: str, req: ConnectRequest) -> dict:
    try:
        await asyncio.to_thread(smb.connect, server_id, req.password)
    except Failure as failure:
        raise _fail(failure)
    return {"serverId": server_id, "status": smb.status(server_id)}


@router.post("/{server_id}/disconnect")
async def disconnect(server_id: str) -> dict:
    await asyncio.to_thread(smb.disconnect, server_id)
    return {"serverId": server_id, "status": smb.status(server_id)}


@router.post("/test")
async def test_connection(req: ServerCreate) -> dict:
    """Try a connection without saving it, so the form can validate itself."""
    return await asyncio.to_thread(
        smb.probe, req.host, req.port, req.username, req.password,
        req.domain, req.share_name)
