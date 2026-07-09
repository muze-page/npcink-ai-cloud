#!/usr/bin/env python3
"""Report GitHub Actions release timing from saved JSON or gh CLI output."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class JobTiming:
    name: str
    conclusion: str
    seconds: int | None


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)  # noqa: UP017
    return parsed


def duration_seconds(started_at: str | None, completed_at: str | None) -> int | None:
    started = parse_timestamp(started_at)
    completed = parse_timestamp(completed_at)
    if started is None or completed is None:
        return None
    return max(0, round((completed - started).total_seconds()))


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "n/a"
    minutes, remaining = divmod(seconds, 60)
    if minutes == 0:
        return f"{remaining}s"
    return f"{minutes}m{remaining:02d}s"


def load_run_json(path: Path | None, run_id: str | None, repo: str | None) -> dict[str, Any]:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    if not run_id:
        raise SystemExit("--run-id is required unless --from-file is used")
    command = [
        "gh",
        "run",
        "view",
        run_id,
        "--json",
        "status,conclusion,createdAt,updatedAt,jobs",
    ]
    if repo:
        command.extend(["--repo", repo])
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise SystemExit("gh CLI is required when --from-file is not used") from exc
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr)
        raise SystemExit(exc.returncode) from exc
    return json.loads(completed.stdout)


def collect_job_timings(run: dict[str, Any]) -> list[JobTiming]:
    jobs = run.get("jobs") or []
    timings: list[JobTiming] = []
    for job in jobs:
        timings.append(
            JobTiming(
                name=str(job.get("name") or "(unnamed)"),
                conclusion=str(job.get("conclusion") or job.get("status") or "unknown"),
                seconds=duration_seconds(job.get("startedAt"), job.get("completedAt")),
            )
        )
    return sorted(
        timings,
        key=lambda item: -1 if item.seconds is None else item.seconds,
        reverse=True,
    )


def summarize(run: dict[str, Any]) -> dict[str, Any]:
    jobs = collect_job_timings(run)
    run_seconds = duration_seconds(run.get("createdAt"), run.get("updatedAt"))
    return {
        "status": run.get("status") or "unknown",
        "conclusion": run.get("conclusion") or "unknown",
        "duration_seconds": run_seconds,
        "duration": format_duration(run_seconds),
        "jobs": [
            {
                "name": job.name,
                "conclusion": job.conclusion,
                "duration_seconds": job.seconds,
                "duration": format_duration(job.seconds),
            }
            for job in jobs
        ],
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Release Timing Report",
        "",
        f"- Run status: `{summary['status']}`",
        f"- Run conclusion: `{summary['conclusion']}`",
        f"- Run wall time: `{summary['duration']}`",
        "",
        "| Job | Conclusion | Duration |",
        "| --- | --- | ---: |",
    ]
    for job in summary["jobs"]:
        lines.append(f"| {job['name']} | {job['conclusion']} | {job['duration']} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", nargs="?", help="GitHub Actions run id")
    parser.add_argument("--repo", help="owner/repo for gh run view")
    parser.add_argument("--from-file", type=Path, help="read gh run view JSON from a file")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    argv = sys.argv[1:]
    if argv[:1] == ["--"]:
        argv = argv[1:]
    args = parser.parse_args(argv)

    run = load_run_json(args.from_file, args.run_id, args.repo)
    summary = summarize(run)
    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
