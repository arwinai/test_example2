#!/usr/bin/env python3
"""Harness for the nanoindenter stage belt guard / fixture / pulley
change (see instruction.md). Grades a candidate .SLDASM via the live
SolidWorks COM session, measuring named components directly (Belt Guard,
Fixture, GT2 belt, the GPA40GT2060-B-H6.35/H8 pulley subassemblies)
rather than the overall assembly envelope.

File-identity note: the real, fully-populated stage assembly in this
task family is "YSZ clamp.SLDASM" (146 components in environment/, 141
in solution/) -- "Main.SLDASM" is an abandoned 2-part stub that was
mistakenly registered as the primary input/reference at one point (and
copied, under that same stub content, into every examples/adversarial_*
folder's "adversarial_*.SLDASM" file). environment/ and solution/'s
"YSZ clamp.SLDASM" have been renamed to the standard input.SLDASM /
solution.SLDASM convention as part of this fix; the examples/adversarial_*
folders still need the same fix (their own "YSZ clamp.SLDASM" holds the
real per-example content, not their "adversarial_*.SLDASM" file) --
flagged here since this harness was only verified against solution.SLDASM.

Acceptance criteria -> checks:
  1. Belt Cover covers both pulleys and belt completely
     -> Belt Guard's assembly-space bbox (X/Y footprint) contains both
        pulley subassemblies' and the GT2 belt's bboxes, computed fresh
        against whatever pulley size is actually present (so this
        doubles as the "cover adjusted to the new pulley diameter" check)
  2. Belt cover does not coincide with any bolts or other parts
     -> NOT machine-graded: no reliable interference-detection COM path
        under dynamic dispatch (IModelDocExtension::
        InterferenceDetectionManager isn't reachable this way either,
        confirmed live; same finding as 34_pneumatic_actuator's
        docstring). A naive bounding-box-overlap proxy was tried and
        rejected: nearby pulley-mounting screws' bboxes legitimately
        overlap the guard's bbox in every axis without actually
        touching the thin sheet-metal shell, so it would false-fail the
        reference solution.
  3. Belt cover has mounts
     -> at least one fastener-like component (screw/bolt/hex socket)
        positioned inside Belt Guard's bbox
  4. Belt cover geometry is manufacturable with sheet metal bending and
     welding
     -> Belt Guard.SLDPRT's own feature tree actually uses SolidWorks
        sheet-metal feature types (SheetMetal/SMBaseFlange/EdgeFlange/
        FlatPattern) -- confirmed live these are genuinely present in
        the reference solution's part, not just plausible-looking solid
        geometry
  5. Belt cover can be attached and detached without disassembly of
     other parts
     -> NOT machine-graded: no reliable geometric signal for "can this
        specific fastener be removed without first removing something
        else" without real disassembly-sequence reasoning
  6. Side Plate removed
     -> the baseline's 8 "HX-SHCS 0.25-20x0.625x0.625" screws (the
        side-plate's own mounting hardware; no separate "side plate"
        component exists by that name anywhere in the live assembly
        tree, confirmed live) must be gone
  7. Fixture plate made longer to be able to mount on a t-slot table
     -> Fixture's assembly-space bbox length (X-span, the axis it grows
        along in the reference: 216.5mm -> 276.5mm) increases
        meaningfully over the baseline
  8. Fixture plate added Holes or slots to mount / 9. Holes or slots
     allow M8 bolt mounting
     -> Fixture's cylindrical-hole diameter list gains new holes in the
        M8-clearance range (8.3-8.7mm) that the baseline doesn't have
 10. Added features to make it manufacturable by Milling
     -> NOT machine-graded: no generic, reliable "is this millable"
        geometric signal (fillet/chamfer presence is too weak a proxy
        -- present throughout this model already for unrelated reasons)
 11. Changed Motor shaft pulley / 12. Changed timing belt pulley to be
     60T instead of 40T
     -> the H6.35-bore pulley (confirmed live: this is the one that
        changes; the H8-bore pulley is untouched in the reference,
        matching instruction.md's "the main shaft" -- singular) grows
        in radius consistent with 40T -> 60T (~1.5x)
 13. Did not change pulley thickness or hole diameter
     -> the same pulley's axial thickness and bore diameter stay fixed
 14. Changed pulley covers to fit the pulley
     -> the matching FLANGE_GPA40GT2060-B-H6.35 part's radius grows to
        keep pace with the larger pulley
 15. Adjusted timing belt / 16. Checked that the belt cover is also
     adjusted to the new pulley diameter
     -> GT2 belt's bbox stays reasonably tangent to/spanning both
        pulleys' current (not baseline) positions; the belt-cover
        containment check (item 1 above) already re-derives against
        the CURRENT pulley size every time, so a stale/unadjusted cover
        sized for the old 40T pulley fails that check directly

All baseline values are frozen in tests/task/reference/baseline.json
(captured from a live measurement of environment/input.SLDASM and
environment/GPA40GT2060-B-H6.35.SLDASM) so grading never has to re-open
that 146-component baseline assembly.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _find_ancestor(name, start):
    """Walk up from `start` for a directory containing `name` -- this
    harness may run from its original `<task>/harness/harness.py`
    location or from the Harbor-generated `<task>/tests/task/harness/
    harness.py` copy, which sits two directories deeper."""
    d = start
    for _ in range(6):
        if (d / name).is_dir():
            return d
        d = d.parent
    raise RuntimeError(f"could not find {name!r} above {start}")


_REPO_ROOT = _find_ancestor("common", HERE)
sys.path.insert(0, str(_REPO_ROOT))


from common import solidworks_session as sws  # noqa: E402
from common.harness_base import Harness  # noqa: E402

BASELINE_JSON = HERE.parent / "reference" / "baseline.json"

BELT_GUARD_NAME = "belt guard"
FIXTURE_NAME = "fixture"
GT2_BELT_NAME = "gt2 belt"
PULLEY_H635_NAME = "gpa40gt2060-b-h6.35"
PULLEY_H8_NAME = "gpa40gt2060-b-h8"
SIDE_PLATE_SCREW_NAME = "hx-shcs 0.25-20"
FASTENER_KEYWORDS = ("screw", "bolt", "shcs", "hex socket", "nhx")
SHEET_METAL_FEATURE_TYPES = ("SheetMetal", "SMBaseFlange", "EdgeFlange", "FlatPattern")

CONTAINMENT_TOL_MM = 6.0
FIXTURE_LENGTH_GROWTH_MIN_MM = 20.0
M8_HOLE_LO_MM, M8_HOLE_HI_MM = 8.3, 8.7
PULLEY_GROWTH_MIN_FRAC = 0.30   # 40T->60T is +50%; require at least +30%
THICKNESS_TOL_MM = 0.5
BORE_TOL_MM = 0.15
FLANGE_GROWTH_MIN_FRAC = 0.15

LOW_PROFILE_MAX_MM = 50.0

_dyn = sws.dyn


def _load_baseline():
    with open(BASELINE_JSON, encoding="utf-8") as fh:
        return json.load(fh)


def _component_name(comp):
    try:
        return str(sws.z(comp.Name2))
    except Exception:
        return ""


def _component_box_mm(comp):
    """Assembly-space bbox in mm, or None. GetBox(False, False) --
    GetBox(True, False) ("include hidden bodies") was confirmed live to
    return a wildly bloated box (off by orders of magnitude) on at least
    one multi-body part in this task (Belt Guard); GetBox(False, False)
    matched the part's real geometry in every case checked, same finding
    as 30_shampoo_bottle's harness on a different multi-body part."""
    try:
        box = list(sws.z(comp.GetBox(False, False)))
        if len(box) != 6:
            return None
        return [float(v) * 1000.0 for v in box]
    except Exception:
        return None


def _find_all(comps, needle):
    needle = needle.lower()
    return [c for c in comps if needle in _component_name(c).lower()]


def _find_one(comps, needle):
    found = _find_all(comps, needle)
    return found[0] if found else None


def _contains(outer_mm, inner_mm, tol_mm):
    return all(
        outer_mm[k] - tol_mm <= inner_mm[k] and inner_mm[k + 3] <= outer_mm[k + 3] + tol_mm
        for k in range(3))


def _cylindrical_hole_diameters_mm(mdoc, max_radius_m=0.015, min_radius_m=0.0):
    out = []
    if mdoc is None:
        return out
    try:
        bodies = sws.z(mdoc.GetBodies2(0, False)) or []
    except Exception:
        return out
    for b in bodies:
        b = _dyn(b)
        for face in (sws.z(b.GetFaces) or []):
            face = _dyn(face)
            try:
                surf = _dyn(sws.z(face.GetSurface))
                if not bool(sws.z(surf.IsCylinder)):
                    continue
                d = sws.z(surf.CylinderParams)
                r = float(d[6])
                if r > max_radius_m or r < min_radius_m:
                    continue
                out.append(round(r * 2000.0, 2))
            except Exception:
                continue
    return out


def _disc_radius_mm(box_mm):
    """Radius of a disc-like part from its own bbox -- the larger of the
    Y/Z half-spans (X is the bore/thickness axis for these pulley and
    flange parts, confirmed live)."""
    if box_mm is None:
        return None
    return max(box_mm[4] - box_mm[1], box_mm[5] - box_mm[2]) / 2.0


def _pulley_measurements(candidate_dir):
    """(radius_mm, thickness_mm, bore_mm, flange_radius_mm) for the
    H6.35 pulley and its matching flange -- read directly from the
    sibling GPA40GT2060-B-H6.35.SLDASM next to the candidate assembly,
    the same file-sibling convention every examples/adversarial_*
    folder and environment/solution/ follow.

    Outer radius (pulley and flange) is read from each part's own bbox,
    not a cylindrical-face scan: confirmed live the pulley's outer OD is
    faceted by dozens of GT2-tooth root fillets (0.2-1.35mm diameter --
    nowhere near the real ~38-45mm OD), and the flange's outer edge
    isn't a simple cylinder at all. Bore diameter DOES need the face
    scan (it's the only way to read it at all), but with a >=4mm radius
    floor to exclude those same tooth-fillet faces -- confirmed live
    the genuine 6.35mm bore is the only face left standing above that
    floor."""
    app = sws.attach()
    asm_path = candidate_dir / "GPA40GT2060-B-H6.35.SLDASM"
    if not asm_path.exists():
        return None, None, None, None
    sws.close_all_documents(app)
    doc, opened_here = sws.open_document(app, str(asm_path), doc_type=sws.DOC_ASSEMBLY)
    if doc is None:
        return None, None, None, None
    sws.activate(app, doc)
    radius_mm = thickness_mm = bore_mm = flange_radius_mm = None
    try:
        comps = [_dyn(c) for c in (sws.z(doc.GetComponents)(True) or [])]
        pulley = _find_one(comps, "timing pulley")
        flange = _find_one(comps, "flange_gpa40gt2060")
        if pulley is not None:
            mdoc = _dyn(sws.z(pulley.GetModelDoc2))
            bore = _cylindrical_hole_diameters_mm(mdoc, max_radius_m=0.006, min_radius_m=0.002)
            if bore:
                bore_mm = min(bore)
            box = _component_box_mm(pulley)
            if box is not None:
                thickness_mm = box[3] - box[0]
                radius_mm = _disc_radius_mm(box)
        if flange is not None:
            flange_radius_mm = _disc_radius_mm(_component_box_mm(flange))
    finally:
        if opened_here:
            try:
                app.CloseDoc(sws.z(doc.GetTitle))
            except Exception:
                pass
    return radius_mm, thickness_mm, bore_mm, flange_radius_mm


def _belt_guard_is_sheet_metal(candidate_dir):
    """Whether Belt Guard.SLDPRT's own feature tree uses real SolidWorks
    sheet-metal feature types (see module docstring)."""
    app = sws.attach()
    part_path = candidate_dir / "Belt Guard.SLDPRT"
    if not part_path.exists():
        return False
    sws.close_all_documents(app)
    doc = sws.open_part_readonly_invisible(app, str(part_path))
    if doc is None:
        return False
    try:
        feat = sws.z(doc.FirstFeature)
        while feat is not None:
            try:
                t = str(sws.z(feat.GetTypeName2))
            except Exception:
                t = ""
            if t in SHEET_METAL_FEATURE_TYPES:
                return True
            feat = sws.z(feat.GetNextFeature)
    finally:
        try:
            app.CloseDoc(sws.z(doc.GetTitle))
        except Exception:
            pass
    return False


def _safe_check(name, fn):
    """Run check fn(); on exception return (False, traceback) instead of
    crashing or silently returning False with no diagnostic."""
    try:
        ok, detail = fn()
        return bool(ok), str(detail)
    except Exception:
        tb = traceback.format_exc()
        return False, f"EXCEPTION in {name}: {tb.strip()}"


class NanoindenterStageHarness(Harness):
    # FIX #3: removed "model rebuilds without errors" from MUST_PASS.
    # The reference solution itself has a genuine hard rebuild error in
    # Belt Guard-1 (documented in task.toml notes). Keeping it in MUST_PASS
    # would zero every score including the reference solution's own score.
    MUST_PASS = ()

    # FIX #2: WEIGHTS now mirrors task.toml [[metadata.scoring_components]].
    # The original had SCORING = {} which caused finalize() to assign equal
    # weight to all checks and produce wrong max_score.
    WEIGHTS = {
        "model rebuilds without errors":                        0,
        "belt cover covers both pulleys and the belt (incl. new pulley size)": 1,
        "belt cover is low-profile":                            1,
        "belt cover has mounting fasteners":                    1,
        "belt cover is sheet-metal manufacturable":             1,
        "side plate removed":                                   1,
        "fixture plate lengthened for t-slot mounting":         1,
        "fixture plate has new M8 mounting holes or slots":     1,
        "motor shaft pulley changed to 60T (larger diameter)":  1,
        "pulley thickness and bore diameter unchanged":         1,
        "pulley cover (flange) resized to fit the new pulley":  1,
        "timing belt adjusted to the new pulley layout":        1,
    }

    CANDIDATE_OPTIONAL = True

    def build_state(self, candidate_path):
        app = sws.attach()
        if candidate_path:
            cand_path = Path(candidate_path).resolve()
            doc, opened_here = sws.open_document(
                app, str(cand_path), doc_type=sws.DOC_ASSEMBLY)
        else:
            doc = sws.active_doc(app)
            opened_here = False
            if doc is None:
                raise RuntimeError("no active SolidWorks document and no "
                                   "candidate path given")
            doc = _dyn(doc)
            cand_path = Path(str(sws.z(doc.GetPathName) or "."))

        try:
            try:
                doc.ForceRebuild3(False)
            except Exception:
                pass
            n_errors = 0
            feat = sws.z(doc.FirstFeature)
            while feat is not None:
                try:
                    warn = sws.byref_bool(False)
                    code = feat.GetErrorCode2(warn)
                    is_warning = bool(warn.value)
                except Exception:
                    code, is_warning = sws.z(feat.GetErrorCode), False
                if code and not is_warning:
                    n_errors += 1
                feat = sws.z(feat.GetNextFeature)

            comps = [_dyn(c) for c in (sws.z(doc.GetComponents)(True) or [])]

            belt_guard = _find_one(comps, BELT_GUARD_NAME)
            fixture = _find_one(comps, FIXTURE_NAME)
            gt2_belt = _find_one(comps, GT2_BELT_NAME)
            pulley_h635 = _find_one(comps, PULLEY_H635_NAME)
            pulley_h8 = _find_one(comps, PULLEY_H8_NAME)

            belt_guard_box = _component_box_mm(belt_guard) if belt_guard is not None else None
            fixture_box = _component_box_mm(fixture) if fixture is not None else None
            gt2_belt_box = _component_box_mm(gt2_belt) if gt2_belt is not None else None
            pulley_h635_box = _component_box_mm(pulley_h635) if pulley_h635 is not None else None
            pulley_h8_box = _component_box_mm(pulley_h8) if pulley_h8 is not None else None

            n_side_plate_screws = len(_find_all(comps, SIDE_PLATE_SCREW_NAME))

            fasteners_in_guard = 0
            if belt_guard_box is not None:
                for c in comps:
                    name = _component_name(c).lower()
                    if not any(k in name for k in FASTENER_KEYWORDS):
                        continue
                    box = _component_box_mm(c)
                    if box is None:
                        continue
                    cx = [(box[k] + box[k + 3]) / 2.0 for k in range(3)]
                    if all(belt_guard_box[k] - CONTAINMENT_TOL_MM <= cx[k]
                           <= belt_guard_box[k + 3] + CONTAINMENT_TOL_MM for k in range(3)):
                        fasteners_in_guard += 1

            fixture_holes_mm = []
            if fixture is not None:
                mdoc = _dyn(sws.z(fixture.GetModelDoc2))
                fixture_holes_mm = _cylindrical_hole_diameters_mm(mdoc)
        finally:
            if opened_here:
                try:
                    app.CloseDoc(sws.z(doc.GetTitle))
                except Exception:
                    pass

        radius_mm, thickness_mm, bore_mm, flange_radius_mm = _pulley_measurements(cand_path.parent)
        belt_guard_sheet_metal = _belt_guard_is_sheet_metal(cand_path.parent)

        return {
            "n_rebuild_errors": n_errors,
            "belt_guard_box": belt_guard_box,
            "fixture_box": fixture_box,
            "gt2_belt_box": gt2_belt_box,
            "pulley_h635_box": pulley_h635_box,
            "pulley_h8_box": pulley_h8_box,
            "n_side_plate_screws": n_side_plate_screws,
            "fasteners_in_guard": fasteners_in_guard,
            "fixture_holes_mm": fixture_holes_mm,
            "pulley_h635_radius_mm": radius_mm,
            "pulley_h635_thickness_mm": thickness_mm,
            "pulley_h635_bore_mm": bore_mm,
            "flange_h635_radius_mm": flange_radius_mm,
            "belt_guard_sheet_metal": belt_guard_sheet_metal,
        }

    def checks(self, state):
        baseline = _load_baseline()
        registry = {}

        # --- gate: rebuild ---
        def _rebuild():
            ok = state["n_rebuild_errors"] == 0
            return ok, f"{state['n_rebuild_errors']} hard rebuild errors in feature tree"

        # --- 1 & 16: belt cover containment (re-derived vs current pulley size) ---
        def _cover_containment():
            bg = state["belt_guard_box"]
            covered = [state["pulley_h635_box"], state["pulley_h8_box"], state["gt2_belt_box"]]
            if bg is None:
                return False, "Belt Guard component not found in assembly"
            missing = [("h635", state["pulley_h635_box"]),
                       ("h8",   state["pulley_h8_box"]),
                       ("belt", state["gt2_belt_box"])]
            missing_names = [n for n, b in missing if b is None]
            if missing_names:
                return False, f"components not found: {missing_names}"
            fails = []
            for name, b in zip(["pulley_h635", "pulley_h8", "gt2_belt"], covered):
                if not _contains(bg, b, CONTAINMENT_TOL_MM):
                    fails.append(name)
            ok = len(fails) == 0
            detail = ("Belt Guard bbox {}mm contains all three".format(
                [round(v, 1) for v in bg]) if ok else
                f"guard does not contain: {fails}; guard={[round(v,1) for v in bg]}")
            return ok, detail

        # --- NEW 4b: low-profile check ---
        def _low_profile():
            bg = state["belt_guard_box"]
            if bg is None:
                return False, "Belt Guard component not found"
            # The belt runs roughly in the XZ plane of the assembly;
            # height is the Y-span (index 1 and 4). We take the minimum
            # span across all three axes as the "thin" direction --
            # a low-profile guard should have one very small dimension.
            spans = [bg[3] - bg[0], bg[4] - bg[1], bg[5] - bg[2]]
            min_span = min(spans)
            ok = min_span <= LOW_PROFILE_MAX_MM
            return ok, (
                "Belt Guard smallest span {:.1f}mm (must be <= {:.0f}mm for low-profile); "
                "all spans: X={:.1f} Y={:.1f} Z={:.1f}mm".format(
                    min_span, LOW_PROFILE_MAX_MM,
                    spans[0], spans[1], spans[2]))

        # --- 3: mounting fasteners ---
        def _fasteners():
            n = state["fasteners_in_guard"]
            ok = n > 0
            return ok, f"{n} fastener-like components inside Belt Guard bbox"

        # --- 4: sheet metal ---
        def _sheet_metal():
            ok = state["belt_guard_sheet_metal"]
            return ok, ("Belt Guard.SLDPRT has sheet-metal features (SheetMetal/"
                        "SMBaseFlange/EdgeFlange/FlatPattern)" if ok
                        else "Belt Guard.SLDPRT has no SolidWorks sheet-metal features")

        # --- 6: side plate removed ---
        def _side_plate():
            n = state["n_side_plate_screws"]
            base_n = baseline.get("n_side_plate_screws", 8)
            ok = n == 0
            return ok, (f"{n} side-plate screws (HX-SHCS 0.25-20) in assembly "
                        f"(baseline had {base_n}; must be 0)")

        # --- 7: fixture lengthened ---
        # Strategy: check all three axes and pass if ANY axis grew by
        # >= FIXTURE_LENGTH_GROWTH_MIN_MM. This is robust against:
        # (a) re-authored assemblies where the fixture is oriented differently,
        # (b) the original hardcoded X-axis assumption being wrong (the baseline
        #     bbox shows Z-span=245.9mm > X-span=216.5mm, so "largest baseline
        #     span" would have picked Z, but the actual growth in the reference
        #     solution is along X -- confirmed by solution scoring 0 on this check
        #     when axis was chosen by max baseline span).
        def _fixture_length():
            fb = state["fixture_box"]
            bb = baseline["fixture_bbox_mm"]
            if fb is None:
                return False, "Fixture component not found in assembly"
            axis_names = ["X", "Y", "Z"]
            base_spans = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]
            cand_spans = [fb[3] - fb[0], fb[4] - fb[1], fb[5] - fb[2]]
            growths = [cand_spans[i] - base_spans[i] for i in range(3)]
            best_axis = growths.index(max(growths))
            best_growth = growths[best_axis]
            ok = best_growth >= FIXTURE_LENGTH_GROWTH_MIN_MM
            detail_parts = [
                "{}: {:.1f}->{:.1f}mm ({:+.1f}mm)".format(
                    axis_names[i], base_spans[i], cand_spans[i], growths[i])
                for i in range(3)
            ]
            return ok, (
                "Fixture spans: {}; best growth {:+.1f}mm on {} axis "
                "(need >= {:.0f}mm on any axis)".format(
                    ", ".join(detail_parts), best_growth,
                    axis_names[best_axis], FIXTURE_LENGTH_GROWTH_MIN_MM))

        # --- 8 & 9: M8 holes ---
        def _m8_holes():
            cand_holes = state["fixture_holes_mm"]
            base_holes = baseline["fixture_hole_diameters_mm"]
            new_m8 = [h for h in cand_holes if M8_HOLE_LO_MM <= h <= M8_HOLE_HI_MM]
            base_m8 = [h for h in base_holes if M8_HOLE_LO_MM <= h <= M8_HOLE_HI_MM]
            ok = len(new_m8) > len(base_m8)
            return ok, (
                f"M8-clearance holes ({M8_HOLE_LO_MM}-{M8_HOLE_HI_MM}mm): "
                f"candidate has {len(new_m8)}, baseline has {len(base_m8)} "
                f"(need candidate > baseline); new holes: {sorted(set(new_m8))}")

        # --- 11 & 12: 60T pulley (larger radius) ---
        def _pulley_60t():
            r = state["pulley_h635_radius_mm"]
            base_r = baseline["pulley_h635_radius_mm"]
            if r is None:
                return False, "H6.35 pulley radius could not be measured"
            grew = (base_r and (r - base_r) / base_r >= PULLEY_GROWTH_MIN_FRAC)
            return grew, (
                "H6.35 pulley radius: baseline {:.3f}mm -> candidate {:.3f}mm "
                "(ratio {:.3f}, need >= {:.2f})".format(
                    base_r, r, r / base_r if base_r else 0,
                    1 + PULLEY_GROWTH_MIN_FRAC))

        # --- 13: thickness and bore unchanged ---
        def _pulley_dims():
            t = state["pulley_h635_thickness_mm"]
            b = state["pulley_h635_bore_mm"]
            base_t = baseline["pulley_h635_thickness_mm"]
            base_b = baseline["pulley_h635_bore_mm"]
            if t is None or b is None:
                return False, "H6.35 pulley thickness or bore could not be measured"
            t_ok = abs(t - base_t) <= THICKNESS_TOL_MM
            b_ok = abs(b - base_b) <= BORE_TOL_MM
            ok = t_ok and b_ok
            return ok, (
                "thickness: {:.2f}mm (baseline {:.2f}mm, tol {:.1f}mm) {}; "
                "bore: {:.3f}mm (baseline {:.3f}mm, tol {:.2f}mm) {}".format(
                    t, base_t, THICKNESS_TOL_MM, "OK" if t_ok else "FAIL",
                    b, base_b, BORE_TOL_MM, "OK" if b_ok else "FAIL"))

        # --- 14: flange resized ---
        def _flange():
            fr = state["flange_h635_radius_mm"]
            base_fr = baseline["flange_h635_radius_mm"]
            if fr is None:
                return False, "H6.35 flange radius could not be measured"
            grew = (base_fr and (fr - base_fr) / base_fr >= FLANGE_GROWTH_MIN_FRAC)
            return grew, (
                "H6.35 flange radius: baseline {:.3f}mm -> candidate {:.3f}mm "
                "(ratio {:.3f}, need >= {:.2f})".format(
                    base_fr, fr, fr / base_fr if base_fr else 0,
                    1 + FLANGE_GROWTH_MIN_FRAC))

        # --- 15: timing belt spans both pulleys ---
        def _belt():
            belt_box = state["gt2_belt_box"]
            p635 = state["pulley_h635_box"]
            p_h8 = state["pulley_h8_box"]
            if belt_box is None:
                return False, "GT2 belt component not found"
            if p635 is None or p_h8 is None:
                return False, "one or both pulley bboxes missing"
            centers = [
                [(p[k] + p[k + 3]) / 2.0 for k in range(3)]
                for p in (p635, p_h8)
            ]
            fails = []
            for i, c in enumerate(centers):
                for k in (0, 1):
                    if not (belt_box[k] - CONTAINMENT_TOL_MM <= c[k]
                            <= belt_box[k + 3] + CONTAINMENT_TOL_MM):
                        fails.append(f"pulley{'_h635' if i == 0 else '_h8'} axis{k}")
            ok = len(fails) == 0
            return ok, ("GT2 belt bbox spans both pulley centres" if ok
                        else f"belt does not span: {fails}; "
                             f"belt={[round(v,1) for v in belt_box]}")

        # Run all checks through _safe_check so exceptions surface as detail strings
        checks_raw = [
            ("model rebuilds without errors",                        _rebuild),
            ("belt cover covers both pulleys and the belt (incl. new pulley size)", _cover_containment),
            ("belt cover is low-profile",                            _low_profile),
            ("belt cover has mounting fasteners",                    _fasteners),
            ("belt cover is sheet-metal manufacturable",             _sheet_metal),
            ("side plate removed",                                   _side_plate),
            ("fixture plate lengthened for t-slot mounting",         _fixture_length),
            ("fixture plate has new M8 mounting holes or slots",     _m8_holes),
            ("motor shaft pulley changed to 60T (larger diameter)",  _pulley_60t),
            ("pulley thickness and bore diameter unchanged",         _pulley_dims),
            ("pulley cover (flange) resized to fit the new pulley",  _flange),
            ("timing belt adjusted to the new pulley layout",        _belt),
        ]

        # FIX #1: return (name, ok, detail) triples
        for name, fn in checks_raw:
            ok, detail = _safe_check(name, fn)
            registry[name] = (name, ok, detail)

        return registry


main = NanoindenterStageHarness.as_main()

if __name__ == "__main__":
    NanoindenterStageHarness.cli()
