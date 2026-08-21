#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Iterable

from gadget_msc_printer.print_boundary import PrintBoundaryDetector


def replay_file(
    path: Path,
    *,
    chunk_size: int = 16 * 1024,
    idle_timeout_ms: int = 1000,
) -> dict[str, Any]:
    detector = PrintBoundaryDetector()
    boundaries: list[dict[str, Any]] = []
    offset = 0
    started_ns = time.monotonic_ns()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            now_ns = time.monotonic_ns()
            for event in detector.feed(chunk, now_ns):
                boundaries.append(
                    {
                        "end_offset": offset + event.end_offset,
                        "protocol": event.protocol,
                        "reason": event.reason,
                    }
                )
            offset += len(chunk)

    idle_timeout_ns = max(0, idle_timeout_ms) * 1_000_000
    if detector.has_data:
        event = detector.poll(detector.last_data_ns + idle_timeout_ns, idle_timeout_ns)
        if event:
            boundaries.append(
                {
                    "end_offset": offset,
                    "protocol": event.protocol,
                    "reason": event.reason,
                }
            )
    elapsed_ms = (time.monotonic_ns() - started_ns) / 1_000_000
    return {
        "name": path.name,
        "path": str(path),
        "size": offset,
        "chunk_size": chunk_size,
        "elapsed_ms": round(elapsed_ms, 3),
        "boundary_count": len(boundaries),
        "boundaries": boundaries,
    }


def discover_prn(paths: Iterable[Path], limit: int) -> list[Path]:
    candidates: dict[Path, float] = {}
    for path in paths:
        if path.is_file() and path.suffix.lower() == ".prn":
            candidates[path.resolve()] = path.stat().st_mtime
        elif path.is_dir():
            for candidate in path.rglob("*.prn"):
                if candidate.is_file():
                    candidates[candidate.resolve()] = candidate.stat().st_mtime
    ordered = sorted(candidates, key=candidates.get, reverse=True)
    return ordered[:limit] if limit > 0 else ordered


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay captured PRN files through the boundary detector")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--chunk-size", type=int, default=16 * 1024)
    parser.add_argument("--idle-timeout-ms", type=int, default=1000)
    args = parser.parse_args()
    if args.chunk_size < 1 or args.chunk_size > 4 * 1024 * 1024:
        parser.error("--chunk-size must be between 1 and 4194304")
    if args.idle_timeout_ms < 0:
        parser.error("--idle-timeout-ms cannot be negative")

    files = discover_prn(args.paths, args.limit)
    results = [
        replay_file(
            path,
            chunk_size=args.chunk_size,
            idle_timeout_ms=args.idle_timeout_ms,
        )
        for path in files
    ]
    print(json.dumps({"count": len(results), "jobs": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
