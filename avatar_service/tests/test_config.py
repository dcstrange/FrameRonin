from pathlib import Path
from avatar_service.config import load_config, Config


def test_load_config_reads_env_and_defaults(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "GEMINI_API_KEY=g123\n"
        "DASHSCOPE_API_KEY=sk-abc\n"
    )
    cfg = load_config(str(env))
    assert isinstance(cfg, Config)
    assert cfg.gemini_api_key == "g123"
    assert cfg.dashscope_api_key == "sk-abc"
    assert cfg.gemini_image_model == "gemini-3.1-flash-image"  # default
    assert cfg.tripo_model == "Tripo/Tripo-P1.0"               # default
    assert cfg.port == 8800                                    # default
    assert cfg.asset_dir.is_absolute() and cfg.asset_dir.exists()


def test_load_config_overrides(tmp_path):
    env = tmp_path / ".env"
    asset_dir = tmp_path / "myassets"
    env.write_text(
        f"GEMINI_API_KEY=g\nDASHSCOPE_API_KEY=s\nPORT=9000\n"
        f"ASSET_DIR={asset_dir}\nGEMINI_IMAGE_MODEL=gemini-2.5-flash-image\n"
    )
    cfg = load_config(str(env))
    assert cfg.port == 9000
    assert cfg.asset_dir == asset_dir.resolve()
    assert cfg.gemini_image_model == "gemini-2.5-flash-image"
