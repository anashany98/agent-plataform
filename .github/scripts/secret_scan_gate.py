#!/usr/bin/env python3
"""Fail closed on TruffleHog findings without ever printing raw secrets."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def _event_file(event: dict[str, Any]) -> str:
    metadata = event.get("SourceMetadata") or {}
    data = metadata.get("Data") or {}
    git_data = data.get("Git") or {}
    return str(git_data.get("file") or "<unknown>")


def _event_line(event: dict[str, Any]) -> int | str:
    metadata = event.get("SourceMetadata") or {}
    data = metadata.get("Data") or {}
    git_data = data.get("Git") or {}
    return git_data.get("line") or "?"


def _fingerprint(event: dict[str, Any]) -> tuple[str, str, str]:
    detector = str(event.get("DetectorName") or "<unknown>")
    raw = str(event.get("Raw") or "")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return detector, digest, _event_file(event)


def _read_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(sys.stdin, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"Invalid scanner JSON at line {line_number}: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        if not isinstance(value, dict):
            print(f"Invalid scanner event at line {line_number}", file=sys.stderr)
            raise SystemExit(2)
        events.append(value)
    return events


def _verify_canary(events: list[dict[str, Any]], detector: str) -> int:
    matches = [event for event in events if event.get("DetectorName") == detector]
    if not matches:
        print(f"Secret scanner canary failed: detector {detector} produced no finding.")
        return 1
    print(f"Secret scanner canary passed: detector={detector}, findings={len(matches)}.")
    return 0


def _load_allowlist(path: Path) -> set[tuple[str, str, str]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("Unsupported secret-scan allowlist schema")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Secret-scan allowlist entries must be a list")
    allowed: set[tuple[str, str, str]] = set()
    for entry in entries:
        key = (
            str(entry["detector"]),
            str(entry["raw_sha256"]),
            str(entry["file"]),
        )
        if key in allowed:
            raise ValueError(f"Duplicate secret-scan allowlist entry: {key[0]} {key[2]}")
        allowed.add(key)
    return allowed


def _verify_history(events: list[dict[str, Any]], allowlist: Path) -> int:
    allowed = _load_allowlist(allowlist)
    unexpected: list[dict[str, Any]] = []
    allowlisted = 0
    for event in events:
        if _fingerprint(event) in allowed:
            allowlisted += 1
        else:
            unexpected.append(event)

    print(
        "Secret history scan: "
        f"findings={len(events)}, allowlisted={allowlisted}, unexpected={len(unexpected)}."
    )
    for event in unexpected:
        detector, digest, file_name = _fingerprint(event)
        print(
            "UNEXPECTED secret candidate: "
            f"detector={detector}, file={file_name}, line={_event_line(event)}, "
            f"fingerprint={digest[:16]}."
        )
    return 1 if unexpected else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allowlist", type=Path)
    parser.add_argument("--canary-detector")
    args = parser.parse_args()
    if bool(args.allowlist) == bool(args.canary_detector):
        parser.error("choose exactly one of --allowlist or --canary-detector")

    events = _read_events()
    if args.canary_detector:
        return _verify_canary(events, args.canary_detector)
    return _verify_history(events, args.allowlist)


if __name__ == "__main__":
    raise SystemExit(main())
