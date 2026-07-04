from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    gemini_api_key: str
    dashscope_api_key: str
    gemini_image_model: str
    tripo_model: str
    asset_dir: Path
    asset_base_url: str
    port: int


def load_config(env_path: str | None = None) -> Config:
    load_dotenv(env_path, override=True)
    asset_dir = Path(os.environ.get("ASSET_DIR", "assets")).resolve()
    asset_dir.mkdir(parents=True, exist_ok=True)
    return Config(
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        gemini_image_model=os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image"),
        tripo_model=os.environ.get("TRIPO_MODEL", "Tripo/Tripo-P1.0"),
        asset_dir=asset_dir,
        asset_base_url=os.environ.get("ASSET_BASE_URL", ""),
        port=int(os.environ.get("PORT", "8800")),
    )
