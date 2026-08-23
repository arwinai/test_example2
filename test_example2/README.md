# SolidWorks RL Environment — Mouse Wheel & Nanoindenter Stage

A test RL environment containing two SolidWorks CAD tasks: `SolidWorks/9_mouse_wheel` and `SolidWorks/16_nanoindenter_stage`. The goal of this repo is to **update — and potentially completely rewrite — the currently AI-generated grading harnesses** for these tasks: the scripts that score a candidate part/assembly against each task's rubric. The current harnesses at `tests/task/harness/harness.py` are the starting point, not a fixed reference; treat them as replaceable so long as the grading contract below is honored.

## First step: fetch the assets

The (very) large SolidWorks files (input models, solutions, examples) live in Azure Blob Storage, not git — the checkout only has their URLs and checksums in each `task.toml`. Before doing anything else, run:

```bash
pip install -r env_requirements.txt   # pywin32 installs on Windows only
python3 tools/fetch.py
```

This downloads every missing or checksum-mismatched asset into place. Nothing in this repo works without it.

## The tasks

See each task's `instruction.md` for the exact prompt.

- **`9_mouse_wheel`** — a single-part task (`.SLDPRT`): edit a mouse shell to add symmetric snap-fit tabs between the shell halves, add two thumb buttons matching the design language, lengthen the mouse from 95 mm to 105 mm, and enlarge the scroll wheel radius by 10%.
- **`16_nanoindenter_stage`** — an assembly task (`.SLDASM` with many component parts): add a low-profile, easily removable belt guard over the belt; remove the side plate and extend the fixture plate for M8 mounting screws; and replace the 40T GT2 pulley on the main shaft with a 60T GT2 pulley.

## Layout of a task

Inside each `SolidWorks/<task>/`:

| Path | Purpose |
|---|---|
| `instruction.md` | The prompt. |
| `task.toml` | Task definition: metadata, scoring components, asset URLs/checksums, environment config. |
| `environment/` | The starting model and a (non-runnable, see below) Dockerfile. For `9_mouse_wheel` this is a single `input.SLDPRT`; for `16_nanoindenter_stage` it is the full assembly (`Main.SLDASM` plus its component parts and sub-assemblies). |
| `solution/` | The reference answer — the "right" edit, which should score full marks (`solution.SLDPRT` for the mouse; `solution.SLDASM` plus its components for the stage). |
| `examples/` | Candidate models to **test the harness against**: mostly adversarial near-misses (tabs unpaired across the seam, elliptical wheel, a 48T pulley substituted for the 60T, a guard that leaves the belt exposed, M6 holes instead of M8, rebuild-error-riddled trees, …). In `9_mouse_wheel` each example is a single `.SLDPRT`; in `16_nanoindenter_stage` each example is a folder containing a full candidate assembly. |
| `tests/` | The harness to update/rewrite (`tests/task/harness/harness.py`), frozen baseline measurements of the input model (`tests/task/prompt/input.json` for the mouse, `tests/task/reference/baseline.json` for the stage), and the verifier entrypoint (`test.sh`). |

The harnesses import shared measurement/capture/scoring code from a `common/` package at the repo root (`solidworks_measure.py`, `solidworks_capture.py`, `harness_base.py`, …).

## The harness

The harness grades **geometry only** (mass properties, centroids, face areas, and — for the assembly task — component placement), never feature or body names — candidates may remodel freely. It scores against the components declared in `task.toml` (`[[metadata.scoring_components]]`) and prints a JSON score envelope (`{"score", "max_score", "passed", "subscores"}`; see `common/harness_base.py`). The scoring components themselves are also yours to edit: if you split, merge, reweight, or add components while reworking a harness, update `[[metadata.scoring_components]]` in that task's `task.toml` to match — the two must stay in sync.

To validate a harness, run it over the reference solution (should score full marks) and every entry in `examples/`.

## Running it — Windows + SolidWorks required

SolidWorks cannot run headlessly or in a container: the harness drives a live, licensed SolidWorks session on Windows via COM (`pywin32`). Run it locally on a Windows machine with SolidWorks installed (you can also use WSL):

```bat
cd SolidWorks\9_mouse_wheel
python tests\task\harness\harness.py path\to\candidate.SLDPRT
```

```bat
cd SolidWorks\16_nanoindenter_stage
python tests\task\harness\harness.py path\to\candidate\solution.SLDASM
```
