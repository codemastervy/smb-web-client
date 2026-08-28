"""JSON-file persistence with atomic writes."""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

from ..config import DATA_DIR

log = logging.getLogger(__name__)
_lock = threading.RLock()


class JsonStore:
    def __init__(self, filename: str, default: Any):
        self.path = DATA_DIR / filename
        self._default = default

    def read(self) -> Any:
        with _lock:
            try:
                return json.loads(self.path.read_text())
            except FileNotFoundError:
                return json.loads(json.dumps(self._default))
            except ValueError:
                broken = self.path.with_suffix(".corrupt")
                log.error("%s is not valid JSON; kept at %s", self.path, broken)
                try:
                    self.path.replace(broken)
                except OSError:
                    pass
                return json.loads(json.dumps(self._default))

    def write(self, data: Any) -> None:
        with _lock:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            with open(tmp, "w") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            tmp.replace(self.path)
            try:
                # Saved credentials live in here, encrypted. Keep the file
                # unreadable to anyone but the service user regardless.
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def update(self, mutator) -> Any:
        with _lock:
            data = self.read()
            result = mutator(data)
            self.write(data)
            return result


servers_store = JsonStore("servers.json", {"servers": []})
prefs_store = JsonStore("preferences.json", {})
settings_store = JsonStore("settings.json", {})
