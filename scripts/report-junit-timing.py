#!/usr/bin/env python3
"""Render slow pytest cases from a JUnit XML report."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TestCaseTiming:
    name: str
    seconds: float


def _case_name(case: ET.Element) -> str:
    classname = case.attrib.get("classname", "").strip()
    name = case.attrib.get("name", "").strip()
    if classname and name:
        return f"{classname}::{name}"
    return name or classname or "(unnamed)"


def collect_test_timings(path: Path) -> list[TestCaseTiming]:
    root = ET.parse(path).getroot()
    timings: list[TestCaseTiming] = []
    for case in root.iter("testcase"):
        raw_seconds = case.attrib.get("time", "0")
        try:
            seconds = max(0.0, float(raw_seconds))
        except ValueError:
            seconds = 0.0
        timings.append(TestCaseTiming(name=_case_name(case), seconds=seconds))
    return sorted(timings, key=lambda item: item.seconds, reverse=True)


def summarize(path: Path, top: int) -> dict[str, Any]:
    timings = collect_test_timings(path)
    total_seconds = sum(item.seconds for item in timings)
    return {
        "path": str(path),
        "count": len(timings),
        "total_seconds": round(total_seconds, 3),
        "slowest": [
            {"name": item.name, "seconds": round(item.seconds, 3)}
            for item in timings[:top]
        ],
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "## Pytest Timing Report",
        "",
        f"- Source: `{summary['path']}`",
        f"- Test cases: `{summary['count']}`",
        f"- Total recorded test time: `{summary['total_seconds']:.3f}s`",
        "",
        "| Test | Seconds |",
        "| --- | ---: |",
    ]
    for item in summary["slowest"]:
        lines.append(f"| `{item['name']}` | {item['seconds']:.3f} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit_xml", type=Path)
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    argv = sys.argv[1:]
    if argv[:1] == ["--"]:
        argv = argv[1:]
    args = parser.parse_args(argv)

    if args.top < 1:
        raise SystemExit("--top must be greater than zero")
    if not args.junit_xml.is_file():
        raise SystemExit(f"JUnit XML report not found: {args.junit_xml}")

    summary = summarize(args.junit_xml, args.top)
    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
