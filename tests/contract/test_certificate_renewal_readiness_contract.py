from __future__ import annotations

import datetime as dt
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "certificate-renewal-readiness.sh"
TIMER = "certbot-renew.timer"
TIMER_SERVICE = "certbot-renew.service"
CERTIFICATE_PATH = Path("/etc/letsencrypt/live/cloud.npc.ink/fullchain.pem")
PRIVATE_KEY_PATH = Path("/etc/letsencrypt/live/cloud.npc.ink/privkey.pem")
CERTIFICATE_REAL_PATH = Path(
    "/etc/letsencrypt/archive/cloud.npc.ink/fullchain1.pem"
)
PRIVATE_KEY_REAL_PATH = Path("/etc/letsencrypt/archive/cloud.npc.ink/privkey1.pem")


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _systemd_exec_start(
    executable: str,
    *arguments: str,
    ignore_errors: str = "no",
) -> str:
    argv = shlex.join((executable, *arguments))
    return (
        f"{{ path={executable} ; argv[]={argv} ; ignore_errors={ignore_errors} ; "
        "start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }"
    )


def _fake_environment(
    tmp_path: Path,
) -> tuple[dict[str, str], Path, Path, Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "commands.log"
    reload_state_path = tmp_path / "nginx-reloads.log"
    cert_path = CERTIFICATE_PATH
    nginx_template_path = ROOT / "deploy" / "magick-domain-nginx.conf.template"
    evidence_path = tmp_path / "evidence" / "certificate-renewal-readiness.json"
    evidence_path.parent.mkdir(mode=0o700)
    hook_dir = tmp_path / "etc" / "letsencrypt" / "renewal-hooks" / "deploy"
    hook_dir.mkdir(parents=True, mode=0o700)
    hook_path = hook_dir / "reload-nginx"

    _write_executable(
        bin_dir / "id",
        """#!/usr/bin/env bash
if [ "${1:-}" = "-u" ]; then
  printf '%s\n' "${FAKE_UID:-0}"
else
  /usr/bin/id "$@"
fi
""",
    )
    _write_executable(
        bin_dir / "stat",
        """#!/usr/bin/env bash
format="${2:-}"
path="${*: -1}"
case "${format}" in
  %F)
    if [ "${path}" = "${FAKE_CERT_PATH:-}" ]; then
      printf '%s\n' "${FAKE_CERT_LINK_TYPE:-symbolic link}"
    elif [ "${path}" = "${FAKE_KEY_PATH:-}" ]; then
      printf '%s\n' "${FAKE_KEY_LINK_TYPE:-symbolic link}"
    elif [ "${path}" = "${FAKE_CERT_REAL_PATH:-}" ]; then
      printf '%s\n' "${FAKE_CERT_REAL_TYPE:-regular file}"
    elif [ "${path}" = "${FAKE_KEY_REAL_PATH:-}" ]; then
      printf '%s\n' "${FAKE_KEY_REAL_TYPE:-regular file}"
    elif [[ "${path}" = /etc/letsencrypt* ]]; then
      printf 'directory\n'
    elif [ -d "${path}" ]; then
      printf 'directory\n'
    elif [ -f "${path}" ]; then
      printf 'regular file\n'
    else
      exit 1
    fi
    ;;
  %u)
    if [ "${path}" = "${FAKE_EVIDENCE_PATH:-}" ]; then
      printf '%s\n' "${FAKE_EVIDENCE_OWNER:-0}"
    elif [ "${path}" = "${FAKE_HOOK_PATH:-}" ]; then
      printf '%s\n' "${FAKE_HOOK_OWNER:-0}"
    elif [ "${path}" = "${FAKE_CERTBOT_PATH:-}" ]; then
      printf '%s\n' "${FAKE_CERTBOT_OWNER:-0}"
    elif [ "${path}" = "${FAKE_CERT_REAL_PATH:-}" ]; then
      printf '%s\n' "${FAKE_CERT_REAL_OWNER:-0}"
    elif [ "${path}" = "${FAKE_KEY_REAL_PATH:-}" ]; then
      printf '%s\n' "${FAKE_KEY_REAL_OWNER:-0}"
    else
      printf '0\n'
    fi
    ;;
  %a)
    if [ "${path}" = "${FAKE_EVIDENCE_PATH:-}" ]; then
      printf '%s\n' "${FAKE_EVIDENCE_MODE:-600}"
    elif [ "${path}" = "${FAKE_HOOK_PATH:-}" ]; then
      printf '%s\n' "${FAKE_HOOK_MODE:-755}"
    elif [ "${path}" = "${FAKE_CERTBOT_PATH:-}" ]; then
      printf '%s\n' "${FAKE_CERTBOT_MODE:-755}"
    elif [ "${path}" = "${FAKE_CERT_REAL_PATH:-}" ]; then
      printf '%s\n' "${FAKE_CERT_REAL_MODE:-644}"
    elif [ "${path}" = "${FAKE_KEY_REAL_PATH:-}" ]; then
      printf '%s\n' "${FAKE_KEY_REAL_MODE:-600}"
    elif [ -n "${FAKE_UNSAFE_PARENT:-}" ] && \
        [ "${path}" = "${FAKE_UNSAFE_PARENT}" ]; then
      printf '777\n'
    elif [ -d "${path}" ]; then
      printf '700\n'
    else
      printf '600\n'
    fi
    ;;
  *) exit 2 ;;
esac
""",
    )
    _write_executable(
        bin_dir / "readlink",
        """#!/usr/bin/env bash
path="${*: -1}"
if [ "${path}" = "${FAKE_CERT_PATH:-}" ]; then
  printf '%s\n' "${FAKE_CERT_REAL_PATH}"
elif [ "${path}" = "${FAKE_KEY_PATH:-}" ]; then
  printf '%s\n' "${FAKE_KEY_REAL_PATH}"
else
  /usr/bin/readlink "$@"
fi
""",
    )
    _write_executable(
        bin_dir / "systemctl",
        """#!/usr/bin/env bash
printf 'systemctl %s\n' "$*" >>"${FAKE_COMMAND_LOG}"
case "${1:-}" in
  is-enabled)
    [ "${*: -1}" = "${FAKE_TIMER_NAME}" ]
    [ "${FAKE_TIMER_ENABLED:-1}" = "1" ]
    ;;
  is-active)
    service="${*: -1}"
    if [ "${service}" = "${FAKE_TIMER_NAME}" ]; then
      [ "${FAKE_TIMER_ACTIVE:-1}" = "1" ]
    elif [ "${service}" = "nginx" ]; then
      [ "${FAKE_NGINX_ACTIVE:-1}" = "1" ]
    else
      exit 2
    fi
    ;;
  show)
    unit="${2:-}"
    property=""
    for token in "$@"; do
      case "${token}" in
        --property=*) property="${token#--property=}" ;;
      esac
    done
    if [ "${unit}" = "${FAKE_TIMER_NAME}" ] && \
        [ "${property}" = "NextElapseUSecRealtime" ]; then
      printf '%s\n' "${FAKE_TIMER_NEXT_RUN:-Tue 2026-07-21 03:00:00 CST}"
    elif [ "${unit}" = "${FAKE_TIMER_NAME}" ] && [ "${property}" = "Unit" ]; then
      printf '%s\n' "${FAKE_TIMER_SERVICE-}"
    elif [ "${unit}" = "${FAKE_TIMER_SERVICE-}" ] && \
        [ "${property}" = "ExecStart" ]; then
      printf '%s\n' "${FAKE_SERVICE_EXEC_START-}"
    elif [ "${unit}" = "nginx" ] && [ "${property}" = "ExecReload" ]; then
      if [ -s "${FAKE_RELOAD_STATE}" ]; then
        cat "${FAKE_RELOAD_STATE}"
      else
        printf 'never\n'
      fi
    else
      exit 2
    fi
    ;;
  reload)
    [ "${2:-}" = "nginx" ]
    [ "${FAKE_NGINX_RELOAD:-1}" = "1" ] || exit 1
    printf 'reload\n' >>"${FAKE_RELOAD_STATE}"
    ;;
  *) exit 2 ;;
esac
""",
    )
    _write_executable(
        bin_dir / "certbot",
        """#!/usr/bin/env bash
printf 'certbot %s\n' "$*" >>"${FAKE_COMMAND_LOG}"
[ "${FAKE_CERTBOT_SUCCESS:-1}" = "1" ]
""",
    )
    _write_executable(
        bin_dir / "mv",
        """#!/usr/bin/env bash
/bin/mv "$@"
[ "${FAKE_MV_REPORT_FAILURE:-0}" != "1" ]
""",
    )
    _write_executable(
        bin_dir / "nginx",
        """#!/usr/bin/env bash
printf 'nginx %s\n' "$*" >>"${FAKE_COMMAND_LOG}"
if [ "${1:-}" = "-T" ]; then
  [ "${FAKE_NGINX_DUMP_SUCCESS:-1}" = "1" ] || exit 1
  sed \
    -e 's|__DOMAIN__|cloud.npc.ink|g' \
    -e "s|__SSL_CERT__|${FAKE_NGINX_CERT_PATH}|g" \
    -e "s|__SSL_KEY__|${FAKE_NGINX_KEY_PATH}|g" \
    -e 's|__UPSTREAM__|http://127.0.0.1:8010|g' \
    "${FAKE_NGINX_TEMPLATE_PATH}"
else
  [ "${FAKE_NGINX_TEST:-1}" = "1" ]
fi
""",
    )
    _write_executable(
        bin_dir / "openssl",
        """#!/usr/bin/env bash
printf 'openssl %s\n' "$*" >>"${FAKE_COMMAND_LOG}"
case "${1:-}" in
  s_client)
    [ "${FAKE_SERVED_CONNECT:-1}" = "1" ]
    printf 'fake served certificate\n'
    ;;
  x509)
    input_path=""
    output_path=""
    previous=""
    for token in "$@"; do
      if [ "${previous}" = "-in" ]; then input_path="${token}"; fi
      if [ "${previous}" = "-out" ]; then output_path="${token}"; fi
      previous="${token}"
    done
    if [[ " $* " = *" -pubkey "* ]]; then
      printf 'certificate-public-key\n'
    elif [[ " $* " = *" -outform PEM "* ]]; then
      cat >/dev/null
      [ "${FAKE_SERVED_PARSE:-1}" = "1" ]
      if [ "${FAKE_SERVED_MATCH:-1}" = "1" ]; then
        printf 'served-match\n' >"${output_path}"
      else
        printf 'served-mismatch\n' >"${output_path}"
      fi
    elif [[ " $* " = *" -checkhost "* ]]; then
      if [ "${input_path}" = "${FAKE_CERT_PATH}" ]; then
        [ "${FAKE_CERT_DOMAIN_MATCH:-1}" = "1" ]
      else
        [ "${FAKE_SERVED_DOMAIN_MATCH:-1}" = "1" ]
      fi
    elif [[ " $* " = *" -checkend "* ]]; then
      if [ "${input_path}" = "${FAKE_CERT_PATH}" ]; then
        [ "${FAKE_CERT_VALIDITY:-1}" = "1" ]
      else
        [ "${FAKE_SERVED_VALIDITY:-1}" = "1" ]
      fi
    elif [[ " $* " = *" -fingerprint -sha256 "* ]]; then
      if [ "${input_path}" != "${FAKE_CERT_PATH}" ] && \
          [ "$(tr -d '\n' <"${input_path}")" = "served-mismatch" ]; then
        printf 'SHA256 Fingerprint=%s\n' \
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
      else
        printf 'SHA256 Fingerprint=%s\n' \
          'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
      fi
    else
      exit 2
    fi
    ;;
  pkey)
    if [[ " $* " = *" -pubin "* ]]; then
      cat
    elif [[ " $* " = *" -pubout "* ]]; then
      if [ "${FAKE_PRIVATE_KEY_MATCH:-1}" = "1" ]; then
        printf 'certificate-public-key\n'
      else
        printf 'different-private-key\n'
      fi
    elif [[ " $* " = *" -check "* ]]; then
      [ "${FAKE_PRIVATE_KEY_VALID:-1}" = "1" ]
    else
      exit 2
    fi
    ;;
  *) exit 2 ;;
esac
""",
    )
    _write_executable(
        hook_path,
        """#!/usr/bin/env bash
set -Eeuo pipefail
printf 'deploy-hook %s\n' "$0" >>"${FAKE_COMMAND_LOG}"
[ "${FAKE_HOOK_SUCCESS:-1}" = "1" ]
[ "${FAKE_HOOK_NOOP:-0}" != "1" ] || exit 0
nginx -t
systemctl reload nginx
""",
    )

    env = os.environ.copy()
    certbot_path = str((bin_dir / "certbot").resolve())
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "NPCINK_CLOUD_RELEASE_TOOL_PYTHON": sys.executable,
            "FAKE_COMMAND_LOG": str(log_path),
            "FAKE_EVIDENCE_PATH": str(evidence_path),
            "FAKE_HOOK_PATH": str(hook_path),
            "FAKE_CERT_PATH": str(cert_path),
            "FAKE_KEY_PATH": str(PRIVATE_KEY_PATH),
            "FAKE_CERT_REAL_PATH": str(CERTIFICATE_REAL_PATH),
            "FAKE_KEY_REAL_PATH": str(PRIVATE_KEY_REAL_PATH),
            "FAKE_NGINX_CERT_PATH": str(cert_path),
            "FAKE_NGINX_KEY_PATH": str(PRIVATE_KEY_PATH),
            "FAKE_NGINX_TEMPLATE_PATH": str(nginx_template_path),
            "FAKE_TIMER_NAME": TIMER,
            "FAKE_TIMER_SERVICE": TIMER_SERVICE,
            "FAKE_CERTBOT_PATH": certbot_path,
            "FAKE_SERVICE_EXEC_START": _systemd_exec_start(
                certbot_path, "-q", "renew"
            ),
            "FAKE_RELOAD_STATE": str(reload_state_path),
        }
    )
    return env, cert_path, evidence_path, hook_path, log_path


def _run(
    mode: str,
    env: dict[str, str],
    cert_path: Path,
    evidence_path: Path,
    hook_path: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            mode,
            "--domain",
            "cloud.npc.ink",
            "--certificate-path",
            str(cert_path),
            "--owner",
            "certbot",
            "--timer",
            TIMER,
            "--deploy-hook-path",
            str(hook_path),
            "--evidence-path",
            str(evidence_path),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _generate(
    env: dict[str, str],
    cert_path: Path,
    evidence_path: Path,
    hook_path: Path,
) -> subprocess.CompletedProcess[str]:
    result = _run("generate", env, cert_path, evidence_path, hook_path)
    assert result.returncode == 0, result.stderr
    return result


def test_generate_and_verify_bind_timer_hook_and_served_leaf_without_cert_bytes(
    tmp_path: Path,
) -> None:
    env, cert_path, evidence_path, hook_path, log_path = _fake_environment(tmp_path)

    _generate(env, cert_path, evidence_path, hook_path)
    result = _run("verify", env, cert_path, evidence_path, hook_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["contract"] == "npcink_cloud_certificate_renewal_readiness.v1"
    assert payload["status"] == "passed"
    assert payload["renewal_owner"] == "certbot"
    assert payload["timer"] == TIMER
    assert payload["renewal_service"] == TIMER_SERVICE
    assert payload["certbot_real_path"] == env["FAKE_CERTBOT_PATH"]
    assert len(payload["renewal_exec_start_sha256"]) == 64
    assert payload["deploy_hook_path"] == str(hook_path)
    assert len(payload["deploy_hook_sha256"]) == 64
    assert payload["certificate_leaf_sha256_fingerprint"] == "a" * 64
    assert payload["certificate_path"] == str(cert_path)
    assert payload["certificate_real_path"] == str(CERTIFICATE_REAL_PATH)
    assert payload["private_key_path"] == str(PRIVATE_KEY_PATH)
    assert payload["private_key_real_path"] == str(PRIVATE_KEY_REAL_PATH)
    assert payload["certificate_private_key_match"] is True
    assert payload["nginx_ssl_certificate_path"] == str(cert_path)
    assert payload["nginx_ssl_certificate_key_path"] == str(PRIVATE_KEY_PATH)
    assert len(payload["nginx_tls_binding_sha256"]) == 64
    assert payload["nginx_references_certbot_lineage"] is True
    assert payload["served_leaf_matches_certificate"] is True
    assert payload["minimum_validity_days"] == 30
    serialized = json.dumps(payload).lower()
    assert "fake pem leaf" not in serialized
    assert "fake served certificate" not in serialized
    command_log = log_path.read_text(encoding="utf-8")
    assert (
        "certbot renew --dry-run --cert-name cloud.npc.ink --run-deploy-hooks"
        in command_log
    )
    assert command_log.count("deploy-hook ") == 2
    assert command_log.count("systemctl reload nginx") == 2
    assert (
        f"systemctl show {TIMER} --property=Unit --value" in command_log
    )
    assert (
        f"systemctl show {TIMER_SERVICE} --property=ExecStart --value"
        in command_log
    )
    assert "openssl s_client -connect 127.0.0.1:443" in command_log
    assert "nginx -T" in command_log


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    (
        ("FAKE_CERT_LINK_TYPE", "regular file", "certificate path must be a Certbot live symlink"),
        ("FAKE_KEY_LINK_TYPE", "regular file", "private-key path must be a Certbot live symlink"),
        (
            "FAKE_CERT_REAL_TYPE",
            "symbolic link",
            "certificate archive target must be a regular non-symlink file",
        ),
        (
            "FAKE_KEY_REAL_TYPE",
            "symbolic link",
            "private-key archive target must be a regular non-symlink file",
        ),
        ("FAKE_CERT_REAL_OWNER", "1000", "certificate archive target must be owned by root"),
        ("FAKE_KEY_REAL_OWNER", "1000", "private-key archive target must be owned by root"),
        (
            "FAKE_KEY_REAL_MODE",
            "640",
            "private-key archive target must not grant group or other permissions",
        ),
    ),
)
def test_generate_rejects_unsafe_certbot_lineage_metadata(
    tmp_path: Path, variable: str, value: str, message: str
) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    env[variable] = value

    result = _run("generate", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert message in result.stderr
    assert not evidence_path.exists()


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    (
        (
            "FAKE_CERT_REAL_PATH",
            "/tmp/copied/fullchain.pem",
            "certificate path must resolve within its Certbot archive lineage",
        ),
        (
            "FAKE_KEY_REAL_PATH",
            "/tmp/copied/privkey.pem",
            "private-key path must resolve within its Certbot archive lineage",
        ),
    ),
)
def test_generate_rejects_live_symlink_target_outside_certbot_archive(
    tmp_path: Path, variable: str, value: str, message: str
) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    env[variable] = value

    result = _run("generate", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert message in result.stderr
    assert not evidence_path.exists()


def test_generate_rejects_certificate_private_key_mismatch(tmp_path: Path) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    env["FAKE_PRIVATE_KEY_MATCH"] = "0"

    result = _run("generate", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert "certificate and private key do not match" in result.stderr
    assert not evidence_path.exists()


@pytest.mark.parametrize(
    ("variable", "value"),
    (
        ("FAKE_NGINX_CERT_PATH", "/etc/nginx/ssl/cloud.npc.ink/fullchain.pem"),
        ("FAKE_NGINX_KEY_PATH", "/etc/nginx/ssl/cloud.npc.ink/privkey.pem"),
    ),
)
def test_generate_rejects_nginx_not_bound_to_configured_certbot_lineage(
    tmp_path: Path, variable: str, value: str
) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    env[variable] = value

    result = _run("generate", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert "NGINX TLS server must reference the configured Certbot live lineage" in result.stderr
    assert not evidence_path.exists()


def test_verify_rejects_nginx_certbot_lineage_binding_drift(tmp_path: Path) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    _generate(env, cert_path, evidence_path, hook_path)
    env["FAKE_NGINX_KEY_PATH"] = "/etc/nginx/ssl/cloud.npc.ink/privkey.pem"

    result = _run("verify", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert "NGINX TLS server must reference the configured Certbot live lineage" in (
        result.stderr
    )


def test_failed_regeneration_atomically_invalidates_prior_success(
    tmp_path: Path,
) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    _generate(env, cert_path, evidence_path, hook_path)
    prior_bytes = evidence_path.read_bytes()
    env["FAKE_CERTBOT_SUCCESS"] = "0"

    failed = _run("generate", env, cert_path, evidence_path, hook_path)

    assert failed.returncode != 0
    assert "Certbot renewal dry run with deploy hooks failed" in failed.stderr
    assert not evidence_path.exists()
    env["FAKE_CERTBOT_SUCCESS"] = "1"
    verified = _run("verify", env, cert_path, evidence_path, hook_path)
    assert verified.returncode != 0
    assert "evidence must be a regular non-symlink file" in verified.stderr
    assert prior_bytes


def test_failed_post_publish_step_cannot_leave_verifiable_evidence(
    tmp_path: Path,
) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    _generate(env, cert_path, evidence_path, hook_path)
    env["FAKE_MV_REPORT_FAILURE"] = "1"

    failed = _run("generate", env, cert_path, evidence_path, hook_path)

    assert failed.returncode != 0
    assert not evidence_path.exists()
    env["FAKE_MV_REPORT_FAILURE"] = "0"
    verified = _run("verify", env, cert_path, evidence_path, hook_path)
    assert verified.returncode != 0


def test_verify_fails_closed_without_evidence(tmp_path: Path) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)

    result = _run("verify", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert "evidence must be a regular non-symlink file" in result.stderr


def test_verify_rejects_stale_evidence(tmp_path: Path) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    _generate(env, cert_path, evidence_path, hook_path)
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    stale = dt.datetime.now(dt.UTC) - dt.timedelta(days=8)
    payload["generated_at_epoch"] = int(stale.timestamp())
    payload["generated_at"] = stale.isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    result = _run("verify", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert "invalid or stale" in result.stderr


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    (
        ("FAKE_TIMER_ENABLED", "0", "timer is not enabled"),
        ("FAKE_TIMER_ACTIVE", "0", "timer is not active"),
        ("FAKE_TIMER_NEXT_RUN", "n/a", "timer has no next run"),
    ),
)
def test_generate_rejects_timer_without_enabled_active_scheduled_state(
    tmp_path: Path, variable: str, value: str, message: str
) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    env[variable] = value

    result = _run("generate", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert message in result.stderr
    assert not evidence_path.exists()


@pytest.mark.parametrize(
    "case",
    (
        "missing-service",
        "wrong-service-noop",
        "shell-wrapper",
        "env-wrapper",
        "wrong-subcommand",
        "misleading-option-value",
        "dry-run-only",
        "directory-hooks-disabled",
        "ignored-error",
        "multiple-commands",
    ),
)
def test_generate_rejects_timer_without_direct_certbot_renew_exec_start(
    tmp_path: Path, case: str
) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    certbot_path = env["FAKE_CERTBOT_PATH"]
    expected_message = "must directly execute the resolved Certbot renew command"
    if case == "missing-service":
        env["FAKE_TIMER_SERVICE"] = ""
        expected_message = "must trigger one explicit service unit"
    elif case == "wrong-service-noop":
        env["FAKE_TIMER_SERVICE"] = "noop-renewal.service"
        env["FAKE_SERVICE_EXEC_START"] = _systemd_exec_start("/bin/true")
    elif case == "shell-wrapper":
        env["FAKE_SERVICE_EXEC_START"] = _systemd_exec_start(
            "/bin/sh", "-c", f"{certbot_path} renew"
        )
    elif case == "env-wrapper":
        env["FAKE_SERVICE_EXEC_START"] = _systemd_exec_start(
            "/usr/bin/env", certbot_path, "renew"
        )
    elif case == "wrong-subcommand":
        env["FAKE_SERVICE_EXEC_START"] = _systemd_exec_start(
            certbot_path, "certificates"
        )
    elif case == "misleading-option-value":
        env["FAKE_SERVICE_EXEC_START"] = _systemd_exec_start(
            certbot_path, "--config-dir", "renew"
        )
    elif case == "dry-run-only":
        env["FAKE_SERVICE_EXEC_START"] = _systemd_exec_start(
            certbot_path, "renew", "--dry-run"
        )
    elif case == "directory-hooks-disabled":
        env["FAKE_SERVICE_EXEC_START"] = _systemd_exec_start(
            certbot_path, "renew", "--no-directory-hooks"
        )
    elif case == "ignored-error":
        env["FAKE_SERVICE_EXEC_START"] = _systemd_exec_start(
            certbot_path, "renew", ignore_errors="yes"
        )
    elif case == "multiple-commands":
        direct = _systemd_exec_start(certbot_path, "renew")
        env["FAKE_SERVICE_EXEC_START"] = f"{direct} {direct}"
    else:  # pragma: no cover - protects the fixture table itself.
        raise AssertionError(case)

    result = _run("generate", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert expected_message in result.stderr
    assert not evidence_path.exists()


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    (
        ("FAKE_CERTBOT_OWNER", "1000", "must be owned by root"),
        ("FAKE_CERTBOT_MODE", "777", "must not be group/world writable"),
    ),
)
def test_generate_rejects_unsafe_resolved_certbot_executable(
    tmp_path: Path, variable: str, value: str, message: str
) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    env[variable] = value

    result = _run("generate", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert message in result.stderr
    assert not evidence_path.exists()


def test_verify_rejects_certbot_executable_that_became_writable(
    tmp_path: Path,
) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    _generate(env, cert_path, evidence_path, hook_path)
    env["FAKE_CERTBOT_MODE"] = "777"

    result = _run("verify", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert "must not be group/world writable" in result.stderr


@pytest.mark.parametrize("drift", ("service", "exec-start"))
def test_verify_rejects_timer_execution_chain_drift(
    tmp_path: Path, drift: str
) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    _generate(env, cert_path, evidence_path, hook_path)
    if drift == "service":
        env["FAKE_TIMER_SERVICE"] = "certbot-nightly.service"
    else:
        env["FAKE_SERVICE_EXEC_START"] = _systemd_exec_start(
            env["FAKE_CERTBOT_PATH"], "-q", "renew", "--quiet"
        )

    result = _run("verify", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert "invalid or stale" in result.stderr


@pytest.mark.parametrize(
    ("variable", "message"),
    (
        ("FAKE_CERT_DOMAIN_MATCH", "certificate does not match"),
        ("FAKE_CERT_VALIDITY", "certificate expires within"),
        ("FAKE_SERVED_DOMAIN_MATCH", "served TLS leaf does not match"),
        ("FAKE_SERVED_VALIDITY", "served TLS leaf expires within"),
    ),
)
def test_generate_rejects_pem_or_served_leaf_domain_and_validity_failure(
    tmp_path: Path, variable: str, message: str
) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    env[variable] = "0"

    result = _run("generate", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert message in result.stderr
    assert not evidence_path.exists()


def test_generate_rejects_served_leaf_fingerprint_mismatch(tmp_path: Path) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    env["FAKE_SERVED_MATCH"] = "0"

    result = _run("generate", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert "served TLS leaf does not match the specified PEM leaf" in result.stderr
    assert not evidence_path.exists()


@pytest.mark.parametrize(
    ("variable", "message"),
    (
        ("FAKE_HOOK_SUCCESS", "deploy hook execution failed"),
        ("FAKE_NGINX_RELOAD", "deploy hook execution failed"),
        ("FAKE_NGINX_TEST", "deploy hook execution failed"),
    ),
)
def test_generate_rejects_hook_or_reload_failure(
    tmp_path: Path, variable: str, message: str
) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    env[variable] = "0"

    result = _run("generate", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert message in result.stderr
    assert not evidence_path.exists()


def test_generate_rejects_successful_noop_hook_without_reload(tmp_path: Path) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    env["FAKE_HOOK_NOOP"] = "1"

    result = _run("generate", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert "did not execute the NGINX reload action" in result.stderr
    assert not evidence_path.exists()


@pytest.mark.parametrize("variable", ("FAKE_HOOK_SUCCESS", "FAKE_NGINX_RELOAD"))
def test_verify_rejects_hook_or_reload_failure(
    tmp_path: Path, variable: str
) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    _generate(env, cert_path, evidence_path, hook_path)
    env[variable] = "0"

    result = _run("verify", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert "deploy hook execution failed" in result.stderr


def test_generate_rejects_symlink_hook(tmp_path: Path) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    target = hook_path.with_name("real-reload-nginx")
    hook_path.rename(target)
    hook_path.symlink_to(target)

    result = _run("generate", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert "regular non-symlink" in result.stderr
    assert not evidence_path.exists()


def test_generate_rejects_dangerous_hook_parent(tmp_path: Path) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    env["FAKE_UNSAFE_PARENT"] = str(hook_path.parent)

    result = _run("generate", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert "must not be group/world writable" in result.stderr
    assert not evidence_path.exists()


def test_verify_rejects_hook_digest_change(tmp_path: Path) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    _generate(env, cert_path, evidence_path, hook_path)
    hook_path.write_text(hook_path.read_text(encoding="utf-8") + "# changed\n")

    result = _run("verify", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert "invalid or stale" in result.stderr


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    (
        ("FAKE_EVIDENCE_MODE", "644", "mode 0600"),
        ("FAKE_EVIDENCE_OWNER", "1000", "owned by root"),
    ),
)
def test_verify_rejects_unsafe_evidence_metadata(
    tmp_path: Path, variable: str, value: str, message: str
) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    _generate(env, cert_path, evidence_path, hook_path)
    env[variable] = value

    result = _run("verify", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert message in result.stderr


def test_generate_is_root_only(tmp_path: Path) -> None:
    env, cert_path, evidence_path, hook_path, _ = _fake_environment(tmp_path)
    env["FAKE_UID"] = "1000"

    result = _run("generate", env, cert_path, evidence_path, hook_path)

    assert result.returncode != 0
    assert "must run as root" in result.stderr


def test_production_call_sites_require_all_bound_env_before_image_mutation() -> None:
    loader = (ROOT / "deploy" / "remote-load-and-up.sh").read_text(encoding="utf-8")
    cutover = (ROOT / "deploy" / "runtime-data-encryption-cutover.sh").read_text(
        encoding="utf-8"
    )

    required_names = (
        "NPCINK_CLOUD_CERTIFICATE_RENEWAL_CERT_PATH",
        "NPCINK_CLOUD_CERTIFICATE_RENEWAL_EVIDENCE_PATH",
        "NPCINK_CLOUD_CERTIFICATE_RENEWAL_TIMER",
        "NPCINK_CLOUD_CERTIFICATE_RENEWAL_HOOK_PATH",
    )
    loader_gate = "# Renewal evidence is verified before snapshot/tag/load can mutate images."
    assert loader_gate in loader
    assert loader.index(loader_gate) < loader.index("\tprepare_release_images\nfi")
    assert 'bash "${CERTIFICATE_RENEWAL_READINESS}" verify' in loader
    assert '--timer "${timer_name}"' in loader
    assert '--deploy-hook-path "${deploy_hook_path}"' in loader
    for name in required_names:
        assert f"Formal runtime requires {name}." in loader

    renewal_stage = 'CURRENT_STAGE="verify-certificate-renewal-readiness"'
    edge_stage = 'CURRENT_STAGE="verify-local-docker-and-host-edge"'
    image_stage = 'CURRENT_STAGE="prepare-exact-bundle-images"'
    assert cutover.index(renewal_stage) < cutover.index(edge_stage) < cutover.index(
        image_stage
    )
    assert 'certificate-renewal-readiness.sh" verify' in cutover
    assert '--timer "${CURRENT_CERTIFICATE_RENEWAL_TIMER}"' in cutover
    assert '--deploy-hook-path "${CURRENT_CERTIFICATE_RENEWAL_HOOK_PATH}"' in cutover
    for name in required_names:
        assert f"current env must define {name}" in cutover
    assert "certbot.timer" not in loader
    assert "certbot.timer" not in cutover
