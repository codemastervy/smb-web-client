"""Browsing and file operations on a connected server."""
from __future__ import annotations

import asyncio
import mimetypes
import urllib.parse

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query,
                     Request, UploadFile)
from fastapi.responses import StreamingResponse

from ..auth import require_auth
from ..config import MAX_UPLOAD_BYTES
from ..models import DeleteRequest, MkdirRequest, RenameRequest, TransferRequest
from ..services import servers, smb, transfers
from ..services.failures import Failure

router = APIRouter(prefix="/api/files", tags=["files"],
                   dependencies=[Depends(require_auth)])


def _fail(failure: Failure) -> HTTPException:
    return HTTPException(status_code=failure.http_status,
                         detail=failure.to_dict())


def _label(server_id: str) -> str:
    profile = servers.get(server_id)
    return profile["name"] if profile else server_id


@router.get("/list")
async def list_directory(serverId: str = Query(...), path: str = Query("/"),
                         showHidden: bool = Query(False)) -> dict:
    try:
        return await asyncio.to_thread(smb.listdir, serverId, path, showHidden)
    except Failure as failure:
        raise _fail(failure)


@router.get("/search")
async def search(serverId: str = Query(...), path: str = Query("/"),
                 q: str = Query(...), recursive: bool = Query(False),
                 showHidden: bool = Query(False)) -> dict:
    try:
        return await asyncio.to_thread(smb.search, serverId, path, q,
                                       recursive, showHidden)
    except Failure as failure:
        raise _fail(failure)


@router.post("/mkdir")
async def mkdir(req: MkdirRequest) -> dict:
    try:
        return await asyncio.to_thread(smb.mkdir, req.server_id, req.parent,
                                       req.name)
    except Failure as failure:
        raise _fail(failure)


@router.post("/rename")
async def rename(req: RenameRequest) -> dict:
    try:
        return await asyncio.to_thread(smb.rename, req.server_id, req.path,
                                       req.new_name)
    except Failure as failure:
        raise _fail(failure)


@router.post("/copy")
async def copy(req: TransferRequest) -> dict:
    return await _run_transfer(req, move=False)


@router.post("/move")
async def move(req: TransferRequest) -> dict:
    return await _run_transfer(req, move=True)


async def _run_transfer(req: TransferRequest, move: bool) -> dict:
    label = _label(req.server_id)
    name = f"{len(req.sources)} item(s)" if len(req.sources) != 1 \
        else req.sources[0].rsplit("/", 1)[-1]
    transfer_id = transfers.start(name, "move" if move else "copy", label)
    try:
        result = await asyncio.to_thread(smb.transfer, req.server_id,
                                         req.sources, req.destination, move)
    except Failure as failure:
        transfers.finish(transfer_id, "failed", failure.message)
        raise _fail(failure)

    if result["failed"]:
        transfers.finish(transfer_id, "failed", result["failed"][0]["error"])
    else:
        transfers.finish(transfer_id, "completed")
    return result


@router.post("/delete")
async def delete(req: DeleteRequest) -> dict:
    try:
        return await asyncio.to_thread(smb.delete, req.server_id, req.paths)
    except Failure as failure:
        raise _fail(failure)


@router.post("/upload")
async def upload(request: Request, serverId: str = Form(...),
                 path: str = Form("/"),
                 file: UploadFile = File(...)) -> dict:
    filename = (file.filename or "upload").rsplit("/", 1)[-1]

    # Cheap early reject on the declared size, so an obviously-too-big upload
    # is refused before a byte reaches the share. Advisory only -- the header
    # is client-supplied, so write_file enforces the real limit while
    # streaming.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise _fail(Failure("too_large", _label(serverId)))

    transfer_id = transfers.start(filename, "upload", _label(serverId))

    def progress(written: int) -> None:
        transfers.progress(transfer_id, written)

    try:
        result = await asyncio.to_thread(smb.write_file, serverId, path,
                                         filename, file.file, progress,
                                         MAX_UPLOAD_BYTES)
    except Failure as failure:
        transfers.finish(transfer_id, "failed", failure.message)
        raise _fail(failure)
    finally:
        await file.close()

    transfers.finish(transfer_id, "completed")
    return result


@router.get("/download")
async def download(serverId: str = Query(...), path: str = Query(...),
                   inline: bool = Query(False)):
    try:
        info = await asyncio.to_thread(smb.stat, serverId, path)
    except Failure as failure:
        raise _fail(failure)
    if info["isDir"]:
        raise HTTPException(status_code=400,
                            detail="cannot download a folder directly")

    name = info["name"]
    transfer_id = transfers.start(name, "download", _label(serverId),
                                  info.get("size"))

    def stream():
        sent = 0
        try:
            for chunk in smb.read_file(serverId, path):
                sent += len(chunk)
                transfers.progress(transfer_id, sent)
                yield chunk
            transfers.finish(transfer_id, "completed")
        except Failure as failure:
            transfers.finish(transfer_id, "failed", failure.message)
            raise
        except Exception as exc:  # noqa: BLE001
            transfers.finish(transfer_id, "failed", str(exc))
            raise

    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    headers = {
        "Content-Disposition":
            f"{'inline' if inline else 'attachment'}; "
            f"filename*=UTF-8''{urllib.parse.quote(name)}",
        "Accept-Ranges": "none",
    }
    if info.get("size") is not None:
        headers["Content-Length"] = str(info["size"])

    return StreamingResponse(stream(), media_type=media_type, headers=headers)
