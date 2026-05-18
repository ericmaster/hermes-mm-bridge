"""Configuration for the Hermes-Mattermost Bridge."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    port: int = 3088
    log_dir: Path = field(default_factory=lambda: Path.home() / "hermes-mm-bridge" / "logs")

    # Optional auth: HMAC-like token that Mattermost sends in Authorization header
    hermes_token: str = ""


def load_config() -> Config:
    """Build Config from environment variables."""
    cfg = Config(
        port=int(os.environ.get("HERMES_MM_BRIDGE_PORT", "3088")),
        log_dir=Path(os.environ.get("LOG_DIR", str(Path.home() / "hermes-mm-bridge" / "logs"))),
        hermes_token=os.environ.get("HERMES_TOKEN", ""),
    )
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def setup_logging(cfg: Config) -> None:
    """Configure logging to file and stdout."""
    log_file = cfg.log_dir / "bridge.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )
