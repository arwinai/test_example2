#!/bin/bash
# TODO: not automatable here. The reference answer would be
# solution/solution.SLDASM (the stage with the low-profile removable belt
# guard, the side plate removed, the fixture plate extended with M8
# mounting holes, and the 60T GT2 pulley on the main shaft), but NO
# SOLUTION MODEL EXISTS in this checkout yet -- solution/ holds only this
# script, and environment/ holds only input.png (no starting Main.SLDASM
# either). Both must be supplied before this task can be solved or
# graded. There is also no headless way to "apply" a SolidWorks assembly
# inside a container -- SolidWorks has to actually open and rebuild the
# files through its own GUI/COM session.
#
# Locally on Windows this would look something like:
#   1. Open solution/solution.SLDASM in SolidWorks (or make the belt-guard /
#      fixture-plate / pulley changes from scratch per instruction.md,
#      starting from environment/input.SLDASM)
#   2. Save the top assembly
#   3. Run tests/task/harness/harness.py against it
set -euo pipefail
echo "TODO: no automated oracle -- see comments in this file" >&2
exit 1
