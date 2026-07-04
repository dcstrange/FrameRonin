from __future__ import annotations

import threading
import uuid
from pathlib import Path


class JobStore:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        jid = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[jid] = {
                "job_id": jid, "status": "pending",
                "progress": None, "result": None, "error": None,
            }
        return jid

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)


class AssetStore:
    def __init__(self, asset_dir: Path):
        self.asset_dir = Path(asset_dir)
        self.asset_dir.mkdir(parents=True, exist_ok=True)

    def save(self, job_id: str, ext: str, data: bytes) -> str:
        filename = f"{job_id}.{ext}"
        (self.asset_dir / filename).write_bytes(data)
        return filename

    def path(self, filename: str) -> Path:
        return self.asset_dir / filename
