#!/bin/bash
# TODO: not runnable in a container. tests/task/harness/harness.py grades
# the SolidWorks document that is currently open and active via COM
# (win32com), or a path passed as argv[1] that it loads into a live
# SolidWorks session -- either way it needs a real, licensed, GUI SolidWorks
# process on Windows, which this environment cannot provide (see
# environment/Dockerfile).
#
# Run locally on Windows instead, from this task's directory:
#   python tests/task/harness/harness.py <path-to-candidate.SLDPRT>
#   # or, to grade whatever is currently open in SolidWorks:
#   python tests/task/harness/harness.py
#
# It prints a JSON score envelope to stdout (see common/harness_base.py's
# finalize()): {"score": ..., "max_score": 8, "passed": ..., "subscores": {...}}
set -euo pipefail
echo "TODO: no automated verifier here -- see comments in this file" >&2
mkdir -p /logs/verifier

fetch_asset() {
  python3 - "$1" "$2" "$3" <<'FETCH'
import hashlib, os, sys, urllib.request
url, sha, dest = sys.argv[1:4]
def ok():
    return (os.path.exists(dest) and
            hashlib.sha256(open(dest, "rb").read()).hexdigest() == sha)
if not ok():
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    urllib.request.urlretrieve(url, dest)
    assert ok(), f"asset checksum mismatch: {dest}"
FETCH
}

fetch_asset "https://openaievalsetub0ktk.blob.core.windows.net/assets/SolidWorks/9_mouse_wheel/tests/task/prompt/input.SLDPRT" "e226dd063df80aa5bf70526824c1e85cf7c27e97a42aa6e7be1741bce0e99c93" "/tests/task/prompt/input.SLDPRT"
 2>/dev/null || true
exit 1
