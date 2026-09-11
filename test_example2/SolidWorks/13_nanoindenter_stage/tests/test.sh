#!/bin/bash
# TODO: not runnable in a container. tests/task/harness/harness.py would
# grade the SolidWorks assembly that is currently open and active via COM
# (win32com), or a path passed as argv[1] that it loads into a live
# SolidWorks session -- either way it needs a real, licensed, GUI
# SolidWorks process on Windows, which this environment cannot provide
# (see environment/Dockerfile).
#
# Checks: harness.py is currently a PLACEHOLDER -- build_state() raises
# "harness not implemented yet", so a grading attempt surfaces as
# could-not-verify rather than fake scores. The real checks (belt guard
# coverage / low profile / removability, side plate removed, fixture
# plate M8 holes, 60T pulley on the main shaft) are blocked on the
# missing environment/ baseline and solution/ models -- see harness.py's
# module docstring.
#
# Run locally on Windows instead, from this task's directory:
#   python tests/task/harness/harness.py <path-to-candidate-assembly>
#   # or, to grade whatever is currently open in SolidWorks:
#   python tests/task/harness/harness.py
#
# It prints a JSON score envelope to stdout (see common/harness_base.py's
# finalize()): {"score": ..., "max_score": ..., "passed": ..., "subscores": {...}}
set -euo pipefail
echo "TODO: no automated verifier here -- see comments in this file" >&2
mkdir -p /logs/verifier

# This task's assets are pinned as whole folders (task.toml's
# [[metadata.assets]], one manifest per examples/* folder), same as
# 34_pneumatic_actuator: fetch anything missing or stale straight off
# the task.toml manifests.
TASK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$TASK_DIR" 2>/dev/null <<'FETCH' || true
import hashlib, os, sys, tomllib, urllib.parse, urllib.request
task_dir = sys.argv[1]

def ok(dest, sha):
    return os.path.exists(dest) and hashlib.sha256(open(dest, "rb").read()).hexdigest() == sha

def download(url, dest, sha):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    urllib.request.urlretrieve(url, dest)
    assert ok(dest, sha), f"asset checksum mismatch: {dest}"

meta = tomllib.load(open(os.path.join(task_dir, "task.toml"), "rb")).get("metadata", {})
for asset in meta.get("assets", []):
    if "manifest" in asset:
        base = asset["url"].rstrip("/")
        for rel, sha, size in asset["manifest"]:
            dest = os.path.join(task_dir, asset["path"], rel)
            if not ok(dest, sha):
                download(f"{base}/{urllib.parse.quote(rel)}", dest, sha)
    else:
        dest = os.path.join(task_dir, asset["path"])
        if not ok(dest, asset["sha256"]):
            download(asset["url"], dest, asset["sha256"])
FETCH

exit 1
