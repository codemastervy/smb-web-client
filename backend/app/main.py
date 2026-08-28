"""smb-web-client -- a self-hosted SMB client with a web UI.

Client only. This app connects *out* to SMB servers. It does not serve SMB,
does not create or manage shares, and does not expose the container's own
disks. If you want the other half, that is a different project.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, crypto
from .config import (ADMIN_PASSWORD, AUTH_ENABLED, DATA_DIR, LOG_LEVEL,
                     SMB_IDLE_SECONDS)
from .routes import files, misc, servers_routes
from .services import smb

logging.basicConfig(
    level=LOG_LEVEL.upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
# smbprotocol is extremely chatty at DEBUG and will drown everything else.
logging.getLogger("smbprotocol").setLevel(logging.WARNING)
logging.getLogger("smbclient").setLevel(logging.WARNING)
log = logging.getLogger("smb-web-client")

app = FastAPI(
    title="smb-web-client",
    description="Self-hosted SMB client. Connects out to SMB shares; does not "
                "host or manage any.",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.include_router(misc.auth_router)
app.include_router(servers_routes.router)
app.include_router(files.router)
app.include_router(misc.transfers_router)
app.include_router(misc.prefs_router)


def _check_data_dir_writable() -> None:
    """Fail with an explanation rather than a bare EACCES traceback.

    This container runs as a non-root user, so a bind-mounted host directory
    owned by someone else is the single most likely first-run problem.
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = DATA_DIR / ".write_test"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        uid = os.getuid()
        raise RuntimeError(
            f"{DATA_DIR} is not writable by uid {uid} ({exc}). "
            f"This app runs as a non-root user. If you bind-mounted a host "
            f"directory, fix its ownership first:  "
            f"sudo chown -R {uid}:{uid} <your data dir>  -- or use the named "
            f"volume the shipped docker-compose.yml uses."
        ) from exc


@app.on_event("startup")
async def startup() -> None:
    _check_data_dir_writable()

    if AUTH_ENABLED and not ADMIN_PASSWORD:
        log.error(
            "ADMIN_PASSWORD is not set. The API is REFUSING to serve until "
            "you set one. This app stores credentials to your file server "
            "and is reachable by anything on your network.")
    elif not AUTH_ENABLED:
        log.warning("AUTH_ENABLED=false -- this app is unauthenticated and "
                    "holds your SMB credentials. Do not do this on a network "
                    "with guests or IoT devices.")

    if not crypto.available():
        log.warning("no key material available: SMB passwords cannot be "
                    "saved. Set ADMIN_PASSWORD.")

    asyncio.create_task(_reaper())


async def _reaper() -> None:
    """Close idle SMB sessions so a sleeping NAS is not held awake."""
    interval = max(30, SMB_IDLE_SECONDS // 2)
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(smb.reap_idle)
        except Exception as exc:  # noqa: BLE001 - the reaper must never die
            log.debug("idle reaper: %s", exc)


@app.middleware("http")
async def refuse_when_misconfigured(request: Request, call_next):
    """Fail closed when auth is on but unconfigured."""
    if (AUTH_ENABLED and not ADMIN_PASSWORD
            and request.url.path.startswith("/api/")
            and request.url.path not in {"/api/auth/status", "/api/health"}):
        return JSONResponse(
            status_code=503,
            content={"detail": "ADMIN_PASSWORD is not set. Set it in "
                               "docker-compose.yml (or AUTH_ENABLED=false to "
                               "run without authentication)."},
        )
    return await call_next(request)


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "role": "smb-client",
        "authRequired": auth.auth_required(),
        "credentialEncryption": crypto.available(),
    }


FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", "/app/frontend"))

if (FRONTEND_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"),
              name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        candidate = (FRONTEND_DIR / full_path).resolve()
        if (full_path and candidate.is_file()
                and candidate.is_relative_to(FRONTEND_DIR.resolve())):
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIR / "index.html")
else:
    @app.get("/")
    async def no_frontend() -> dict:
        return {"detail": "frontend build not found; API is at /api/docs"}
