#!/usr/bin/env python3
"""Check published architecture diagram mirrors and Markdown local links across 20 labs.

No network/cloud access, no writes. Run at repository root:
    python scripts/check-diagram-mirrors.py
"""
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
GCP = ROOT / "GCP"
LABS = sorted(path for path in GCP.glob("LAB-*") if path.is_dir())
errors = []
checked_assets = 0
checked_links = 0
if len(LABS) != 20:
    errors.append(f"Expected 20 GCP labs, found {len(LABS)}")

for lab in LABS:
    guide = lab / "README.md"
    diagrams = lab / "assets" / "diagrams"
    primary = diagrams / "solution.svg"
    if not guide.is_file():
        errors.append(f"{lab.name}: README missing")
        continue
    if not primary.is_file():
        errors.append(f"{lab.name}: canonical assets/diagrams/solution.svg missing")
    if not diagrams.is_dir():
        errors.append(f"{lab.name}: assets/diagrams missing")
        continue
    for f in sorted(diagrams.iterdir()):
        if not f.is_file():
            continue
        legacy = lab / "assets" / f.name
        if not legacy.is_file():
            errors.append(f"{lab.name}: missing compatibility mirror for {f.name}")
            continue
        if f.read_bytes() != legacy.read_bytes():
            errors.append(f"{lab.name}: asset differs from mirror: {f.name}")
        checked_assets += 1

    markdown = guide.read_text(encoding="utf-8")
    # Locally referenced Markdown links and images; remote links and anchors excluded.
    for target in re.findall(r"!?(?:\[[^\]]*\])\(([^)]+)\)", markdown):
        local = unquote(target.split("#", 1)[0].split("?", 1)[0].strip())
        if not local or re.match(r"^[a-z][a-z0-9+.-]*:", local, re.I) or local.startswith("//"):
            continue
        if not (lab / local).is_file():
            errors.append(f"{lab.name}: broken Markdown link: {target}")
        checked_links += 1
    if not re.search(r"\]\(assets/diagrams/[^)]+\)", markdown):
        errors.append(f"{lab.name}: README has no canonical diagram link")

if errors:
    print("FAIL: architecture asset / Markdown path audit")
    for message in errors:
        print(" -", message)
    sys.exit(1)
print(f"PASS: {len(LABS)} labs; {checked_assets} diagram mirror pairs; {checked_links} local links")
