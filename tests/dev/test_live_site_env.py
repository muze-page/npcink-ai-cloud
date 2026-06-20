from __future__ import annotations

from pathlib import Path

from app.dev.live_site_env import (
    INTERNAL_TOKEN_ENV_KEY,
    parse_env_file,
    resolve_env_secret,
)


def test_parse_env_file_handles_export_quotes_and_comments(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# ignored",
                "export MAGICK_CLOUD_INTERNAL_AUTH_TOKEN='quoted-token'",
                "OTHER=value # comment",
            ]
        )
    )

    assert parse_env_file(env_file) == {
        "MAGICK_CLOUD_INTERNAL_AUTH_TOKEN": "quoted-token",
        "OTHER": "value",
    }


def test_resolve_env_secret_prefers_cli_then_env_then_last_non_empty_file(
    tmp_path: Path, monkeypatch: object
) -> None:
    env_file = tmp_path / ".env"
    env_local = tmp_path / ".env.local"
    env_file.write_text(f"{INTERNAL_TOKEN_ENV_KEY}=\n")
    env_local.write_text(f'{INTERNAL_TOKEN_ENV_KEY}="file-token-32-bytes-long-value"\n')

    monkeypatch.delenv(INTERNAL_TOKEN_ENV_KEY, raising=False)
    from_file = resolve_env_secret(
        cli_value="",
        env_key=INTERNAL_TOKEN_ENV_KEY,
        env_files=[env_file, env_local],
    )

    assert from_file.value == "file-token-32-bytes-long-value"
    assert from_file.source == f"env_file:{env_local}"
    assert from_file.redacted() == {
        "present": True,
        "source": f"env_file:{env_local}",
        "length": len("file-token-32-bytes-long-value"),
    }

    monkeypatch.setenv(INTERNAL_TOKEN_ENV_KEY, "process-token-32-bytes-long-value")
    from_env = resolve_env_secret(
        cli_value="",
        env_key=INTERNAL_TOKEN_ENV_KEY,
        env_files=[env_file, env_local],
    )
    assert from_env.value == "process-token-32-bytes-long-value"
    assert from_env.source == f"env:{INTERNAL_TOKEN_ENV_KEY}"

    from_cli = resolve_env_secret(
        cli_value="cli-token-32-bytes-long-value",
        env_key=INTERNAL_TOKEN_ENV_KEY,
        env_files=[env_file, env_local],
    )
    assert from_cli.value == "cli-token-32-bytes-long-value"
    assert from_cli.source == "cli"
