"""Transfer tracking for the Transfers panel.

Deliberately in-memory: a transfer is meaningful only while the request that
drives it is alive, and a browser reload should show the current state of the
server, not a resurrected history from last week. Completed entries are kept
briefly so the panel can show what just finished.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Literal, Optional

Direction = Literal["upload", "download", "copy", "move", "delete"]
State = Literal["waiting", "active", "completed", "cancelled", "failed"]

_MAX_HISTORY = 60

_lock = threading.RLock()
_transfers: list[dict[str, Any]] = []


def start(file_name: str, direction: Direction, destination: str,
          total_bytes: Optional[int] = None) -> str:
    entry = {
        "id": uuid.uuid4().hex[:12],
        "fileName": file_name,
        "direction": direction,
        "destinationLabel": destination,
        "transferredBytes": 0,
        "totalBytes": total_bytes,
        "state": "active",
        "startedAt": time.time(),
        "finishedAt": None,
        "error": None,
    }
    with _lock:
        _transfers.append(entry)
        # Trim finished entries first, so an active transfer is never evicted.
        while len(_transfers) > _MAX_HISTORY:
            for i, candidate in enumerate(_transfers):
                if candidate["state"] != "active":
                    _transfers.pop(i)
                    break
            else:
                break
    return entry["id"]


def progress(transfer_id: str, transferred: int,
             total: Optional[int] = None) -> None:
    with _lock:
        for entry in _transfers:
            if entry["id"] == transfer_id:
                entry["transferredBytes"] = transferred
                if total is not None:
                    entry["totalBytes"] = total
                return


def finish(transfer_id: str, state: State = "completed",
           error: Optional[str] = None) -> None:
    with _lock:
        for entry in _transfers:
            if entry["id"] == transfer_id:
                entry["state"] = state
                entry["error"] = error
                entry["finishedAt"] = time.time()
                if state == "completed" and entry["totalBytes"] is None:
                    entry["totalBytes"] = entry["transferredBytes"]
                return


def listing() -> list[dict[str, Any]]:
    with _lock:
        return sorted(_transfers, key=lambda t: t["startedAt"], reverse=True)


def clear_finished() -> int:
    with _lock:
        before = len(_transfers)
        remaining = [t for t in _transfers if t["state"] == "active"]
        _transfers[:] = remaining
        return before - len(remaining)
