from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ENV_FILES = (Path(".env"), Path(".env.local"))
INTERNAL_TOKEN_ENV_KEY = "MAGICK_CLOUD_INTERNAL_AUTH_TOKEN"


@dataclass(frozen=True)
class SecretResolution:
    value: str
    source: str
    length: int

    def redacted(self) -> dict[str, object]:
        return {
            "present": bool(self.value),
            "source": self.source,
            "length": self.length,
        }


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if not key:
            continue
        parsed[key] = _clean_env_value(value)
    return parsed


def _clean_env_value(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    if " #" in text:
        text = text.split(" #", 1)[0].rstrip()
    return text


def resolve_env_secret(
    *,
    cli_value: str,
    env_key: str,
    env_files: list[Path] | tuple[Path, ...] | None,
) -> SecretResolution:
    cli_text = cli_value.strip()
    if cli_text:
        return SecretResolution(value=cli_text, source="cli", length=len(cli_text))

    env_text = str(os.environ.get(env_key) or "").strip()
    if env_text:
        return SecretResolution(value=env_text, source=f"env:{env_key}", length=len(env_text))

    resolved_files = env_files if env_files is not None else DEFAULT_ENV_FILES
    file_value = ""
    file_source = ""
    for env_file in resolved_files:
        values = parse_env_file(env_file)
        if env_key not in values:
            continue
        value = values[env_key].strip()
        if value:
            file_value = value
            file_source = f"env_file:{env_file}"
    if file_value:
        return SecretResolution(value=file_value, source=file_source, length=len(file_value))
    return SecretResolution(value="", source="missing", length=0)


def default_env_files(value: list[Path] | None) -> list[Path]:
    return value if value is not None else list(DEFAULT_ENV_FILES)
