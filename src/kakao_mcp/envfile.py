"""Load/save agent.env next to the executable or project cwd."""
from __future__ import annotations

import os
import sys
from pathlib import Path

AGENT_ENV_KEYS = (
    "KAKAO_AGENT_API_KEY",
    "KAKAO_AGENT_HOST",
    "KAKAO_AGENT_PORT",
    "KAKAO_AGENT_ALLOW_IPS",
    "KAKAO_AGENT_WEBHOOK_URL",
    "KAKAO_ALLOWED_FILE_ROOT",
)


def default_env_path() -> Path:
    """Prefer directory of frozen exe; else cwd."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "agent.env"
    return Path.cwd() / "agent.env"


def load_env_file(path: Path | None = None) -> dict[str, str]:
    path = path or default_env_path()
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value
    return result


def save_env_file(values: dict[str, str], path: Path | None = None) -> Path:
    path = path or default_env_path()
    lines = ["# KakaoTalk Agent local config", ""]
    for key in AGENT_ENV_KEYS:
        lines.append(f"{key}={values.get(key, '')}")
    # preserve any extra keys user may have set
    for key, value in values.items():
        if key not in AGENT_ENV_KEYS:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def apply_env_file_to_os(path: Path | None = None, *, override: bool = True) -> dict[str, str]:
    """Load agent.env into os.environ. Returns loaded map."""
    data = load_env_file(path)
    for key, value in data.items():
        if override or key not in os.environ or not os.environ.get(key):
            os.environ[key] = value
    return data
