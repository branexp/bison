from __future__ import annotations

import os
import pathlib
import tomllib
from dataclasses import dataclass
from typing import Any

from platformdirs import user_config_dir


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://dedi.emailbison.com"
    api_token: str = ""
    timeout_seconds: float = 20.0
    retries: int = 2
    default_timezone: str | None = None

    # Endpoint paths (override only if EmailBison changes these)
    campaigns_path: str = "/api/campaigns"
    campaigns_v11_path: str = "/api/campaigns/v1.1"
    sender_emails_path: str = "/api/sender-emails"


class ConfigError(RuntimeError):
    pass


def _load_toml(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover
        raise ConfigError(f"Failed to parse config TOML: {path}: {e}") from e
    if not isinstance(data, dict):
        return {}
    return data


def default_config_paths() -> list[pathlib.Path]:
    # Precedence (lower → higher): XDG config then legacy homefile
    xdg = pathlib.Path(user_config_dir("emailbison")) / "config.toml"
    legacy = pathlib.Path.home() / ".emailbison.toml"
    return [xdg, legacy]


def load_settings(
    *,
    base_url: str | None = None,
    api_token: str | None = None,
    timeout_seconds: float | None = None,
    retries: int | None = None,
    default_timezone: str | None = None,
    campaigns_path: str | None = None,
) -> Settings:
    """Load settings using precedence:

    1) explicit function args (CLI flags)
    2) env vars
    3) config file(s)
    4) defaults

    Env vars:
    - EMAILBISON_BASE_URL
    - EMAILBISON_API_TOKEN
    - EMAILBISON_TIMEOUT_SECONDS
    - EMAILBISON_RETRIES
    - EMAILBISON_DEFAULT_TIMEZONE
    - EMAILBISON_CAMPAIGNS_PATH
    """

    file_cfg: dict[str, Any] = {}
    for p in default_config_paths():
        file_cfg.update(_load_toml(p))

    env_cfg: dict[str, Any] = {
        "base_url": os.getenv("EMAILBISON_BASE_URL"),
        "api_token": os.getenv("EMAILBISON_API_TOKEN"),
        "timeout_seconds": os.getenv("EMAILBISON_TIMEOUT_SECONDS"),
        "retries": os.getenv("EMAILBISON_RETRIES"),
        "default_timezone": os.getenv("EMAILBISON_DEFAULT_TIMEZONE"),
        "campaigns_path": os.getenv("EMAILBISON_CAMPAIGNS_PATH"),
    }

    def pick(key: str, explicit: Any) -> Any:
        if explicit is not None:
            return explicit
        if env_cfg.get(key) not in (None, ""):
            return env_cfg[key]
        if key in file_cfg and file_cfg[key] not in (None, ""):
            return file_cfg[key]
        return None

    final_base_url = pick("base_url", base_url) or "https://dedi.emailbison.com"
    final_api_token = pick("api_token", api_token)

    if not final_api_token:
        raise ConfigError(
            "Missing api_token. Set EMAILBISON_API_TOKEN or add api_token to config.toml."
        )

    ts = pick("timeout_seconds", timeout_seconds)
    rt = pick("retries", retries)
    tz = pick("default_timezone", default_timezone)
    cp = pick("campaigns_path", campaigns_path)

    try:
        timeout_f = float(ts) if ts is not None else 20.0
    except ValueError as e:
        raise ConfigError("timeout_seconds must be a number") from e

    try:
        retries_i = int(rt) if rt is not None else 2
    except ValueError as e:
        raise ConfigError("retries must be an integer") from e

    return Settings(
        base_url=str(final_base_url).rstrip("/"),
        api_token=str(final_api_token),
        timeout_seconds=timeout_f,
        retries=retries_i,
        default_timezone=str(tz) if tz not in (None, "") else None,
        campaigns_path=str(cp) if cp not in (None, "") else "/api/campaigns",
    )
