#!/usr/bin/env python3
"""Воспроизводимо копирует pinned native schemas из canonical exporter."""

import argparse, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--exporter", required=True, type=Path)
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
source = args.exporter.resolve()
base = "_extensions/course-prairielearn/spec/upstream"
target = ROOT / "schemas/native-upstream"
names = [
    "infoCourse.json",
    "infoCourseInstance.json",
    "infoAssessment.json",
    "infoQuestion.json",
    "PRAIRIELEARN-LICENSE",
    "provenance.json",
]
commit = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=source, text=True
).strip()
for name in names:
    path = source / base / name
    if path.is_symlink() or path.resolve() != path:
        raise SystemExit("Unsafe schema source")
    data = path.read_bytes()
    pinned = subprocess.check_output(
        ["git", "show", commit + ":" + base + "/" + name], cwd=source
    )
    if data != pinned:
        raise SystemExit("Native schema differs from committed provider dependency")
    if args.check:
        if (target / name).read_bytes() != data:
            raise SystemExit("Stale generated native schema")
    else:
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_bytes(data)
print("PASS pinned native schema dependency")
