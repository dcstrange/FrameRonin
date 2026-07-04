from __future__ import annotations

from . import gemini_client, tripo_client
from .config import Config
from .store import AssetStore, JobStore
from .style import build_prompt, pixelate_png


def _default_deps(cfg: Config) -> dict:
    return {
        "generate_image": lambda prompt, **kw: gemini_client.generate_image(
            prompt, api_key=cfg.gemini_api_key, model=cfg.gemini_image_model),
        "submit": lambda img, **kw: tripo_client.with_retry(
            lambda: tripo_client.submit(img, api_key=cfg.dashscope_api_key,
                                        model=cfg.tripo_model), backoff=2),
        "poll": lambda tid, **kw: tripo_client.poll(tid, api_key=cfg.dashscope_api_key),
        "download": lambda url, **kw: tripo_client.with_retry(
            lambda: tripo_client.download(url), backoff=2),
    }


def _url(cfg: Config, filename: str) -> str:
    base = cfg.asset_base_url.rstrip("/") if cfg.asset_base_url else ""
    return f"{base}/assets/{filename}"


def run_job(job_id, req, cfg, jobs: JobStore, assets: AssetStore, *, deps=None) -> None:
    d = deps or _default_deps(cfg)
    style = req.get("style", "3d")
    try:
        jobs.update(job_id, status="running", progress="generating_image")
        prompt = build_prompt(req["prompt"], style=style, shell=req.get("shell"))
        img = d["generate_image"](prompt)

        if style == "pixel":
            png = pixelate_png(img)
            fn = assets.save(job_id, "png", png)
            jobs.update(job_id, progress="done", status="succeeded",
                        result={"glb_url": None, "image_url": _url(cfg, fn)})
            return

        src_fn = assets.save(job_id, "png", img)
        jobs.update(job_id, progress="converting_3d")
        task_id = d["submit"](img)
        glb_url_up = d["poll"](task_id)
        jobs.update(job_id, progress="downloading")
        glb = d["download"](glb_url_up)
        glb_fn = assets.save(job_id, "glb", glb)
        jobs.update(job_id, progress="done", status="succeeded", result={
            "glb_url": _url(cfg, glb_fn),
            "preview_url": _url(cfg, src_fn),      # source image doubles as preview
            "source_image_url": _url(cfg, src_fn),
        })
    except Exception as e:  # noqa: BLE001 — funnel all step failures to job.error
        jobs.update(job_id, status="failed", error=str(e))
