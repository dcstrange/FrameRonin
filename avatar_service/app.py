from __future__ import annotations

import threading

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Config, load_config
from .pipeline import run_job
from .store import AssetStore, JobStore


class AvatarRequest(BaseModel):
    prompt: str
    style: str = "3d"
    shell: str | None = None


def _thread_runner(job_id, req, cfg, jobs, assets):
    threading.Thread(
        target=run_job, args=(job_id, req, cfg, jobs, assets), daemon=True
    ).start()


def create_app(cfg: Config | None = None, *, runner=None) -> FastAPI:
    cfg = cfg or load_config()
    jobs = JobStore()
    assets = AssetStore(cfg.asset_dir)
    run = runner or _thread_runner
    app = FastAPI(title="Avatar 3D Service")

    @app.post("/avatars")
    def create_avatar(req: AvatarRequest):
        if not req.prompt.strip():
            raise HTTPException(status_code=400, detail="prompt is required")
        job_id = jobs.create()
        run(job_id, req.model_dump(), cfg, jobs, assets)
        return {"job_id": job_id, "status": "pending"}

    @app.get("/avatars/{job_id}")
    def get_avatar(job_id: str):
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    app.mount("/assets", StaticFiles(directory=str(cfg.asset_dir)), name="assets")
    return app


def get_app() -> FastAPI:
    """Factory for uvicorn: `uvicorn avatar_service.app:get_app --factory`."""
    return create_app()
