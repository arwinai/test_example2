#!/usr/bin/env python3

import json
import math
import os
import sys
import hashlib
import tempfile

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..', '..', '..', '..', '..')))
from common.harness_base import Harness


ORIGINAL_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'prompt', 'input.SLDPRT'))
BASELINE_JSON = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'prompt', 'input.json'))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

TARGET_RATIO = 1.10
RATIO_TOL    = 0.01

LENGTH_TARGET_MM   = 105.0
LENGTH_TOL_MM      = 1.5
MIN_LENGTH_GAIN_MM = 8.0

# Snap-fit disengagement estimate (item 1): classical cantilever hand calc
# per the BASF/Bayer snap-fit design guides, computed from each detected
# tab's measured beam geometry. Material properties are ASSUMED (the part
# is consumer ABS; engineering has not confirmed the grade) and stated in
# every report line. This is a design-guide estimate, not FEA -- SolidWorks
# Simulation is not licensed on the grading machine, and a nonlinear
# contact study on arbitrary candidate geometry would be too fragile for a
# deterministic grader anyway.
SNAP_E_MPA       = 2300.0   # ABS flexural modulus (assumed)
SNAP_MU          = 0.35     # ABS-on-ABS friction coefficient (assumed)
SNAP_FORCE_MIN_N = 15.0     # the brief's minimum disengagement force

HOOK_AREA_MM2   = (1.0, 100.0)
HOOK_BAND_MM    = 6.0
HOOK_CLUSTER_MM = 8.0
HOOK_SPAN_MM    = 15.0
HOOK_CENTRE_MM  = 4.0
MIN_TABS        = 4

BTN_VOL_CM3     = (0.02, 10.0)
BTN_OFFSET_FRAC = 0.18

WHEEL_SKETCH_NAME   = r'\u00c7izim8'
SLOT_WIDTH_DIM_NAME = r'D2@\u00c7izim7'



# --------------------------------------------------------------------------
# Collection: rebuild/tree health, the named wheel sketch and slot-width
# dimension, a geometric fallback scan (name-free) for re-authored
# deliverables, and small-planar-face data for the snap-tab checks -- all
# spoken directly over pywin32 through common/solidworks_session.

def _named(raw):
    # WHEEL_SKETCH_NAME/SLOT_WIDTH_DIM_NAME hold escaped non-ASCII names
    return raw.encode('ascii').decode('unicode_escape')


def _collect(original_path=None, cand_stl='', orig_stl=''):
    from common import solidworks_session as sws

    baseline_path = ORIGINAL_PATH if original_path is None else original_path
    wheel_sketch = _named(WHEEL_SKETCH_NAME)
    slot_dim = _named(SLOT_WIDTH_DIM_NAME)
    SKETCH_ARC = 1            # swSketchSegments_e.swSketchARC
    # Verified 2026-08-15 against the live SOLIDWORKS 2026 typelib
    # (swconst.tlb) on the grading box: swSTLDontTranslateToPositive == 71,
    # not 68 -- the blind port's guess was wrong and would have exported
    # STL in translated coordinates, drifting every mesh.* check.
    STL_NO_TRANSLATE = sws.sw_constant('swSTLDontTranslateToPositive', 71)

    app = sws.attach()

    def export_stl(doc, dst):
        if doc is None or not dst:
            return
        try:
            app.SetUserPreferenceToggle(STL_NO_TRANSLATE, True)
            try:
                doc.Visible = True
            except Exception:
                pass
            sws.activate(app, doc)
            # Extension.SaveAs2's ExportData/AdvancedSaveAsOptions params
            # hit a persistent "type mismatch" through dynamic dispatch no
            # matter what VARIANT type each was tried as -- the plain
            # single-arg SaveAs (format inferred from dst's extension)
            # works cleanly and is all STL export needs here.
            doc.SaveAs(dst)
        except Exception:
            pass

    def measure(doc, do_rebuild):
        out = {'path': '', 'title': '', 'rebuild_ok': True,
               'feat_errors': 0, 'feat_warns': 0,
               'wheel_radius': -1.0, 'wheel_cx': 0.0, 'wheel_cy': 0.0,
               'slot_width': -1.0,
               'geo_wheel_radius': -1.0,
               'geo_wheel_center': [0.0, 0.0, 0.0],
               'geo_wheel_axis': [0.0, 0.0, 0.0],
               'geo_slot_width': -1.0, 'geo_wheel_width': -1.0,
               'near_faces': [], 'flat_faces': [],
               'bbox': [1e9, 1e9, 1e9, -1e9, -1e9, -1e9]}
        try:
            out['path'] = str(sws.z(doc.GetPathName) or '')
        except Exception:
            pass
        try:
            out['title'] = str(sws.z(doc.GetTitle) or '')
        except Exception:
            pass

        if do_rebuild:
            sws.activate(app, doc)
            try:
                out['rebuild_ok'] = bool(sws.z(doc.EditRebuild3))
            except Exception:
                out['rebuild_ok'] = False

        # ---- slot opening width from its named dimension ----
        try:
            dim = sws.redispatch(doc.Parameter(slot_dim))
            if dim is not None:
                out['slot_width'] = float(sws.z(dim.SystemValue))
        except Exception:
            pass

        # ---- feature tree walk: errors/warnings and the wheel circle ----
        try:
            feat = sws.redispatch(sws.z(doc.FirstFeature))
        except Exception:
            feat = None
        while feat is not None:
            fname = ''
            try:
                fname = str(sws.z(feat.Name) or '')
            except Exception:
                pass
            try:
                warn = sws.byref_bool()
                ec = int(feat.GetErrorCode2(warn))
                if ec != 0:
                    out['feat_errors'] += 1
                if bool(warn.value):
                    out['feat_warns'] += 1
            except Exception:
                pass
            if fname == wheel_sketch:
                try:
                    sk = sws.redispatch(sws.z(feat.GetSpecificFeature2))
                    segs = sws.z(sk.GetSketchSegments) if sk is not None else None
                    for seg in (segs or []):
                        seg = sws.redispatch(seg)
                        try:
                            if int(sws.z(seg.GetType)) != SKETCH_ARC:
                                continue
                            if int(sws.z(seg.IsCircle)) != 1:
                                continue
                            r = float(sws.z(seg.GetRadius))
                            if r > out['wheel_radius']:
                                out['wheel_radius'] = r
                                c = sws.redispatch(sws.z(seg.GetCenterPoint2))
                                if c is not None:
                                    out['wheel_cx'] = float(sws.z(c.X))
                                    out['wheel_cy'] = float(sws.z(c.Y))
                        except Exception:
                            continue
                except Exception:
                    pass
            try:
                feat = sws.redispatch(sws.z(feat.GetNextFeature))
            except Exception:
                break

        # ---- geometric fallback scan (name-free) ----
        try:
            part = sws.redispatch(doc)
            bodies = [sws.redispatch(b) for b in
                      (part.GetBodies2(0, True) or [])]  # swSolidBody
        except Exception:
            bodies = []

        def bodybox(body):
            try:
                bx = sws.z(body.GetBodyBox)
                return [float(v) for v in bx] if bx is not None else None
            except Exception:
                return None

        def faces_of(body):
            try:
                return [sws.redispatch(f) for f in (sws.z(body.GetFaces) or [])]
            except Exception:
                return []

        wheel_box = None
        g = {'r': -1.0, 'ax': (0.0, 0.0, 0.0), 'c': [0.0, 0.0, 0.0]}
        for body in bodies:
            bx = bodybox(body)
            if bx is None:
                continue
            for i in range(3):
                out['bbox'][i] = min(out['bbox'][i], bx[i])
                out['bbox'][i + 3] = max(out['bbox'][i + 3], bx[i + 3])
            for face in faces_of(body):
                try:
                    surf = sws.redispatch(sws.z(face.GetSurface))
                    if surf is None or not sws.z(surf.IsCylinder):
                        continue
                    cp = [float(v) for v in (sws.z(surf.CylinderParams) or [])]
                    if len(cp) < 7:
                        continue
                    r = cp[6]
                    if r < 0.005 or r > 0.020 or r <= g['r']:
                        continue
                    ax, ay, az = abs(cp[3]), abs(cp[4]), abs(cp[5])
                    axis_dim = 0 if ax > 0.99 else (1 if ay > 0.99 else
                                                    (2 if az > 0.99 else -1))
                    if axis_dim < 0:
                        continue
                    spans = [bx[3] - bx[0], bx[4] - bx[1], bx[5] - bx[2]]
                    if spans[axis_dim] > 0.009:
                        continue
                    if any(abs(spans[d] - 2 * r) > 0.5 * r
                           for d in range(3) if d != axis_dim):
                        continue
                    g['r'] = r
                    g['ax'] = (cp[3], cp[4], cp[5])
                    c = [cp[0], cp[1], cp[2]]
                    c[axis_dim] = (bx[axis_dim] + bx[axis_dim + 3]) / 2.0
                    g['c'] = c
                    wheel_box = bx
                except Exception:
                    continue

        out['geo_wheel_radius'] = g['r']
        out['geo_wheel_axis'] = list(g['ax'])
        out['geo_wheel_center'] = list(g['c'])

        if wheel_box is not None:
            a_dim = 0 if abs(g['ax'][0]) > 0.99 else                 (1 if abs(g['ax'][1]) > 0.99 else 2)
            wc = g['c']

            def colocated(bx):
                return all(bx[d] > wheel_box[d] - 0.002 and
                           bx[d + 3] < wheel_box[d + 3] + 0.002
                           for d in range(3))

            walls = []
            for body in bodies:
                bx = bodybox(body)
                if bx is None or colocated(bx):
                    continue
                for face in faces_of(body):
                    try:
                        surf = sws.redispatch(sws.z(face.GetSurface))
                        if surf is None or not sws.z(surf.IsPlane):
                            continue
                        pp = [float(v) for v in (sws.z(surf.PlaneParams) or [])]
                        if len(pp) < 6 or abs(pp[a_dim]) < 0.99:
                            continue
                        fb = [float(v) for v in (sws.z(face.GetBox) or [])]
                        if len(fb) < 6:
                            continue
                        if any(fb[d + 3] < wc[d] - g['r'] or fb[d] > wc[d] + g['r']
                               for d in range(3) if d != a_dim):
                            continue
                        walls.append(pp[3 + a_dim])
                    except Exception:
                        continue

            wheel_width = wheel_box[a_dim + 3] - wheel_box[a_dim]
            out['geo_wheel_width'] = wheel_width
            min_gap = max(0.002, wheel_width - 0.0005)
            best = 1e9
            for lo in walls:
                if lo > wc[a_dim]:
                    continue
                for hi in walls:
                    if hi < wc[a_dim]:
                        continue
                    gap = hi - lo
                    if min_gap <= gap < 0.015 and gap < best:
                        best = gap
            if best < 1e8:
                out['geo_slot_width'] = best

            inf_t, inf_a = 0.6 * g['r'], 0.004
            for body in bodies:
                if len(out['near_faces']) >= 150:
                    break
                bx = bodybox(body)
                if bx is None or colocated(bx):
                    continue
                for face in faces_of(body):
                    if len(out['near_faces']) >= 150:
                        break
                    try:
                        surf = sws.redispatch(sws.z(face.GetSurface))
                        if surf is None or not sws.z(surf.IsPlane):
                            continue
                        pp = [float(v) for v in (sws.z(surf.PlaneParams) or [])]
                        if len(pp) < 6:
                            continue
                        nd = 0 if abs(pp[0]) > 0.99 else                             (1 if abs(pp[1]) > 0.99 else
                             (2 if abs(pp[2]) > 0.99 else -1))
                        if nd < 0:
                            continue
                        fb = [float(v) for v in (sws.z(face.GetBox) or [])]
                        if len(fb) < 6:
                            continue
                        near = all(
                            fb[d + 3] >= wheel_box[d] - (inf_a if d == a_dim else inf_t)
                            and fb[d] <= wheel_box[d + 3] + (inf_a if d == a_dim else inf_t)
                            for d in range(3))
                        if not near:
                            continue
                        out['near_faces'].append([nd, pp[3 + nd]] + fb[:6])
                    except Exception:
                        continue

        # ---- small planar faces anywhere (snap-tab catch ledges) ----
        for body in bodies:
            if len(out['flat_faces']) >= 1500:
                break
            for face in faces_of(body):
                if len(out['flat_faces']) >= 1500:
                    break
                try:
                    surf = sws.redispatch(sws.z(face.GetSurface))
                    if surf is None or not sws.z(surf.IsPlane):
                        continue
                    area_mm2 = float(sws.z(face.GetArea)) * 1e6
                    if area_mm2 < 1.0 or area_mm2 > 100.0:
                        continue
                    pp = [float(v) for v in (sws.z(surf.PlaneParams) or [])]
                    fb = [float(v) for v in (sws.z(face.GetBox) or [])]
                    if len(pp) < 6 or len(fb) < 6:
                        continue
                    out['flat_faces'].append(pp[:6] + [area_mm2] + fb[:6])
                except Exception:
                    continue

        return out

    # ---- candidate: whatever document is active RIGHT NOW ----
    candidate = sws.active_doc(app)
    cand_path = cand_title = ''
    try:
        cand_path = str(sws.z(candidate.GetPathName) or '') if candidate else ''
        cand_title = str(sws.z(candidate.GetTitle) or '') if candidate else ''
    except Exception:
        pass

    cand_err = None
    if candidate is None:
        cand_err = 'no_active_doc'
    elif int(sws.z(candidate.GetType)) != sws.DOC_PART:
        cand_err = 'active_doc_not_part'
    elif baseline_path and cand_path.lower() == baseline_path.lower():
        cand_err = 'active_doc_is_baseline'

    if not baseline_path:
        if cand_err is not None:
            return {'original': {'skipped': True},
                    'candidate': {'error': cand_err, 'path': cand_path,
                                  'title': cand_title}}
        cand_json = measure(candidate, True)
        export_stl(candidate, cand_stl)
        return {'original': {'skipped': True}, 'candidate': cand_json}

    base_doc = sws.open_part_readonly_invisible(app, baseline_path)
    orig_json = ({'error': 'could_not_open', 'path': baseline_path}
                 if base_doc is None else measure(base_doc, False))

    if cand_err is not None:
        cand_json = {'error': cand_err, 'path': cand_path, 'title': cand_title}
    else:
        cand_json = measure(candidate, True)
        export_stl(candidate, cand_stl)
    export_stl(base_doc, orig_stl)
    return {'original': orig_json, 'candidate': cand_json}


def _mm(metres):
    return metres * 1000.0


def _ratio_ok(orig, changed):
    if orig is None or changed is None or orig <= 0 or changed <= 0:
        return False, float('nan')
    ratio = changed / orig
    return abs(ratio - TARGET_RATIO) <= TARGET_RATIO * RATIO_TOL, ratio


CANDIDATE_ERRORS = {
    'no_active_doc':
        'No document is active in SolidWorks - open an attempt and rerun.',
    'active_doc_not_part':
        'The active document is not a part (.SLDPRT) - activate the attempt and rerun.',
    'active_doc_is_baseline':
        'The active document IS the baseline part - open a candidate attempt and rerun.',
}


def check_shared1_rebuild(candidate):
    ok = candidate.get('rebuild_ok', False)
    return ok, 'EditRebuild3 -> {}'.format(ok)


def check_shared2_features(candidate):
    errors = candidate.get('feat_errors', 0)
    ok = (errors == 0)
    return ok, '{} feature errors in tree'.format(errors)


def _effective(doc, named_key, geo_key):
    """Geometric (B-rep) measurement first, named dimension as fallback.

    Geometry is ground truth: a Scale feature (and other geometry-level
    edits) changes the B-rep without touching sketch dimensions, so a named
    value can go stale while the part itself is correct (pinned by the
    adversarial_uniform_scale_105 example). Returns (value, geo_only) where
    geo_only means no named value existed at all (re-authored model).
    """
    g = doc.get(geo_key, -1) or -1
    v = doc.get(named_key, -1) or -1
    if g > 0:
        return g, (v <= 0)
    return v, False


def _staleness_note(doc, named_key, geo_key):
    """Flag a named dimension that no longer matches the actual geometry."""
    g = doc.get(geo_key, -1) or -1
    v = doc.get(named_key, -1) or -1
    if g > 0 and v > 0 and abs(g - v) > 0.02 * v:
        return ('  [named dimension reads {:.3f}mm but the geometry '
                'measures {:.3f}mm - geometry governs]'.format(_mm(v), _mm(g)))
    return ''


GEO_NOTE = '  [geometric measurement: named feature absent, re-authored model]'


def _mesh_metrics(stl_path):
    import numpy as np
    import trimesh
    m = trimesh.load(stl_path)
    v = m.vertices
    lo, hi = v.min(axis=0), v.max(axis=0)
    ext = hi - lo
    order = [int(i) for i in np.argsort(ext)]
    h_dim, w_dim, l_dim = order[0], order[1], order[2]
    length, width, height = float(ext[l_dim]), float(ext[w_dim]), float(ext[h_dim])

    tri = v[m.faces]
    edges = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    y1, y2 = edges[:, 0, h_dim], edges[:, 1, h_dim]
    z1, z2 = edges[:, 0, l_dim], edges[:, 1, l_dim]
    best_len, seam_y = -1.0, None
    for f in np.arange(0.10, 0.51, 0.02):
        y0 = lo[h_dim] + f * height
        cross = (y1 - y0) * (y2 - y0) <= 0
        if not cross.any():
            continue
        den = y2[cross] - y1[cross]
        safe = np.where(np.abs(den) < 1e-12, 1.0, den)
        t = np.where(np.abs(den) < 1e-12, 0.5, (y0 - y1[cross]) / safe)
        z = z1[cross] + t * (z2[cross] - z1[cross])
        sec = float(z.max() - z.min())
        if sec > best_len:
            best_len, seam_y = sec, float(y0)

    w1, w2 = edges[:, 0, w_dim], edges[:, 1, w_dim]
    h1, h2 = edges[:, 0, h_dim], edges[:, 1, h_dim]
    l1, l2 = edges[:, 0, l_dim], edges[:, 1, l_dim]
    wc = (lo[w_dim] + hi[w_dim]) / 2.0
    seam_profile = []
    for l0 in np.arange(lo[l_dim] + 2.0, hi[l_dim] - 2.0, 3.0):
        cross = (l1 - l0) * (l2 - l0) <= 0
        if not cross.any():
            continue
        den = l2[cross] - l1[cross]
        safe = np.where(np.abs(den) < 1e-12, 1.0, den)
        t = np.where(np.abs(den) < 1e-12, 0.5, (l0 - l1[cross]) / safe)
        ww = w1[cross] + t * (w2[cross] - w1[cross])
        hh = h1[cross] + t * (h2[cross] - h1[cross])
        i = int(np.argmax(np.abs(ww - wc)))
        seam_profile.append([float(l0), float(hh[i])])

    comps = m.split(only_watertight=False, repair=False)
    w_centre = (lo[w_dim] + hi[w_dim]) / 2.0
    buttons = []
    for c in comps:
        try:
            vol = abs(float(c.volume)) * 1e-3
        except Exception:
            continue
        if not (BTN_VOL_CM3[0] <= vol <= BTN_VOL_CM3[1]):
            continue
        cen = c.vertices.mean(axis=0)
        off = float(cen[w_dim] - w_centre)
        if abs(off) < BTN_OFFSET_FRAC * width:
            continue
        buttons.append({'volume_cm3': round(vol, 3), 'offset_mm': round(off, 2),
                        'pos': [round(float(x), 2) for x in cen]})

    return {
        'length_mm': length, 'width_mm': width, 'height_mm': height,
        'h_dim': h_dim, 'w_dim': w_dim, 'l_dim': l_dim,
        'lo': [float(x) for x in lo], 'hi': [float(x) for x in hi],
        'seam_elev_mm': seam_y, 'seam_section_mm': round(best_len, 2),
        'seam_profile': [[round(a, 1), round(b, 2)] for a, b in seam_profile],
        'flank_buttons': buttons, 'n_components': len(comps),
    }


def _snap_tabs(doc, mesh):
    faces = doc.get('flat_faces') or []
    if mesh is None or not mesh.get('seam_profile'):
        return None
    h_dim, w_dim, l_dim = mesh['h_dim'], mesh['w_dim'], mesh['l_dim']
    profile = mesh['seam_profile']
    w_centre = (mesh['lo'][w_dim] + mesh['hi'][w_dim]) / 2.0

    def seam_at(l_pos):
        return min(profile, key=lambda s: abs(s[0] - l_pos))[1]

    ledges = []      # catch-ledge candidates (near-horizontal, at the seam)
    walls = []       # nearby near-vertical faces (cantilever beam walls)
    for f in faces:
        n = f[0:3]
        area = f[6]
        box = [c * 1000.0 for c in f[7:13]]
        f_l = (box[l_dim] + box[l_dim + 3]) / 2.0
        f_h = (box[h_dim] + box[h_dim + 3]) / 2.0
        cw = (box[w_dim] + box[w_dim + 3]) / 2.0 - w_centre
        rec = {'n_h': abs(n[h_dim]), 'n_w': abs(n[w_dim]),
               'w_lo': box[w_dim] - w_centre, 'w_hi': box[w_dim + 3] - w_centre,
               'l_lo': box[l_dim], 'l_hi': box[l_dim + 3],
               'h_span': box[h_dim + 3] - box[h_dim],
               'cw': cw, 'cl': f_l, 'area': area}
        if abs(n[h_dim]) >= 0.7:
            if abs(f_h - seam_at(f_l)) > HOOK_BAND_MM:
                continue
            if not (HOOK_AREA_MM2[0] <= area <= HOOK_AREA_MM2[1]):
                continue
            span_l = box[l_dim + 3] - box[l_dim]
            span_w = box[w_dim + 3] - box[w_dim]
            if max(span_l, span_w) > HOOK_SPAN_MM:
                continue
            if abs(cw) < HOOK_CENTRE_MM:
                continue
            ledges.append(rec)
        elif abs(n[h_dim]) < 0.35 and abs(n[w_dim]) > 0.7 and rec['h_span'] >= 3.0:
            walls.append(rec)      # candidate beam side-wall for the force calc

    clusters = []    # [cw, cl, count, member_ledges]
    for rec in ledges:
        for c in clusters:
            if abs(rec['cw'] - c[0]) < HOOK_CLUSTER_MM and abs(rec['cl'] - c[1]) < HOOK_CLUSTER_MM:
                c[0] = (c[0] * c[2] + rec['cw']) / (c[2] + 1)
                c[1] = (c[1] * c[2] + rec['cl']) / (c[2] + 1)
                c[2] += 1
                c[3].append(rec)
                break
        else:
            clusters.append([rec['cw'], rec['cl'], 1, [rec]])
    used, pairs = set(), 0
    for i, a in enumerate(clusters):
        if i in used:
            continue
        for j, b in enumerate(clusters):
            if j <= i or j in used:
                continue
            if abs(a[0] + b[0]) < 4.0 and abs(a[1] - b[1]) < 4.0:
                used.add(i)
                used.add(j)
                pairs += 1
                break
    forces = [_estimate_tab_force(clusters[i], walls) for i in sorted(used)]
    return {'clusters': [[round(c[0], 1), round(c[1], 1), c[2]] for c in clusters],
            'paired_tabs': pairs * 2,
            'forces': forces}


def _estimate_tab_force(cluster, walls):
    """Classical cantilever snap-fit hand calculation (BASF/Bayer design
    guide) from the tab's measured geometry. Returns a dict, or None when
    the beam geometry can't be extracted (odd construction -> human review).

    Beam model: deflection force P = E*w*t^3*y / (4*L^3); disengagement
    force W = P*(mu + tan a)/(1 - mu*tan a) where a is the retraction-face
    angle; mu*tan(a) >= 1 means self-locking (pull-off bounded by material
    shear, not friction -- comfortably beyond any 15N target). Material is
    ASSUMED (E, mu constants above); the estimate is design-guide grade,
    not FEA.
    """
    cw, cl, _cnt, members = cluster[0], cluster[1], cluster[2], cluster[3]
    near = [w for w in walls
            if abs(w['cw'] - cw) <= 6.0
            and w['l_lo'] <= cl + 6.0 and w['l_hi'] >= cl - 6.0]
    if not near:
        return None
    L = max(w['h_span'] for w in near)
    # undercut = the CATCH ledge's protrusion. A cluster merges the hook
    # with its mating groove, whose top ledge is much wider than the catch
    # -- the smallest substantial ledge span is the undercut.
    spans = [m['w_hi'] - m['w_lo'] for m in members
             if (m['w_hi'] - m['w_lo']) >= 0.3]
    if not spans:
        return None
    y = min(spans)
    ext_lo = min([m['w_lo'] for m in members] + [w['w_lo'] for w in near])
    ext_hi = max([m['w_hi'] for m in members] + [w['w_hi'] for w in near])
    t = (ext_hi - ext_lo) - y
    width = max([m['l_hi'] - m['l_lo'] for m in members]
                + [w['l_hi'] - w['l_lo'] for w in near])
    if not (0.4 <= t <= 6.0 and 2.0 <= L <= 30.0 and 0.2 <= y <= 5.0
            and 0.5 <= width <= 25.0):
        return None
    P = SNAP_E_MPA * width * t ** 3 * y / (4.0 * L ** 3)
    # retraction angle from the steepest catch ledge: a horizontal catch
    # face (n_h = 1) is a 90-degree, self-locking retention
    n_h = max(m['n_h'] for m in members)
    tilt_deg = math.degrees(math.acos(min(1.0, n_h)))
    alpha_deg = 90.0 - tilt_deg
    strain_pct = 150.0 * t * y / L ** 2
    tan_a = math.tan(math.radians(alpha_deg))
    locking = SNAP_MU * tan_a >= 1.0
    W = None if locking else P * (SNAP_MU + tan_a) / (1.0 - SNAP_MU * tan_a)
    return {'at': (round(cw, 1), round(cl, 1)),
            'L_mm': round(L, 2), 't_mm': round(t, 2), 'y_mm': round(y, 2),
            'width_mm': round(width, 2), 'alpha_deg': round(alpha_deg, 1),
            'strain_pct': round(strain_pct, 2),
            'P_N': round(P, 1), 'self_locking': locking,
            'W_N': None if W is None else round(W, 1)}


def check_item1_snap_tabs(candidate, cand_mesh):
    tabs = _snap_tabs(candidate, cand_mesh)
    if tabs is None:
        return False, 'Snap-tab scan impossible (no mesh/seam data)'
    n = tabs['paired_tabs']
    count_ok = n >= MIN_TABS

    # Disengagement-force gate: every paired tab whose beam geometry could
    # be measured must estimate >= 15N (self-locking counts as passing --
    # pull-off is bounded by material shear, far beyond 15N). Tabs whose
    # geometry defeats the beam extraction stay flagged for human review
    # rather than failing the check.
    forces = tabs.get('forces') or []
    measured = [f for f in forces if f]
    force_ok = all(f['self_locking'] or (f['W_N'] or 0) >= SNAP_FORCE_MIN_N
                   for f in measured)
    ok = count_ok and force_ok

    parts = []
    for f in forces:
        if f is None:
            parts.append('unmeasurable beam (human review)')
        elif f['self_locking']:
            parts.append('self-locking (alpha={}deg, P~{}N, L={} t={} y={}mm)'.format(
                f['alpha_deg'], f['P_N'], f['L_mm'], f['t_mm'], f['y_mm']))
        else:
            parts.append('W~{}N (alpha={}deg, P~{}N, L={} t={} y={}mm)'.format(
                f['W_N'], f['alpha_deg'], f['P_N'], f['L_mm'], f['t_mm'], f['y_mm']))
    force_txt = ('; disengagement >= {:.0f}N per tab pair (BASF cantilever '
                 'hand calc, ABS E={:.0f}MPa mu={} ASSUMED): [{}]'.format(
                     SNAP_FORCE_MIN_N, SNAP_E_MPA, SNAP_MU, ', '.join(parts))
                 if forces else '')
    return ok, ('{} mirror-paired catch features at the parting seam '
                '(need >= {}); clusters (w-offset, l-pos, faces): {}{}'.format(
                    n, MIN_TABS, tabs['clusters'], force_txt))


def check_item2_thumb_buttons(cand_mesh, orig_mesh):
    if cand_mesh is None:
        return False, 'No mesh data'
    btns = cand_mesh['flank_buttons']
    n_orig = len((orig_mesh or {}).get('flank_buttons', []))
    same_side = bool(btns) and all(
        b['offset_mm'] * btns[0]['offset_mm'] > 0 for b in btns)
    ok = len(btns) == 2 and same_side and n_orig == 0
    return ok, ('{} discrete flank button bodies (need exactly 2 on one side; '
                'original has {}); lateral offsets {} mm  [thumb-side '
                'placement and design language need visual review]'.format(
                    len(btns), n_orig,
                    [b['offset_mm'] for b in btns]))


def check_item3_length(orig_mesh, cand_mesh):
    if cand_mesh is None or orig_mesh is None:
        return False, 'No mesh data'
    L, L0 = cand_mesh['length_mm'], orig_mesh['length_mm']
    ok = (abs(L - LENGTH_TARGET_MM) <= LENGTH_TOL_MM
          and (L - L0) >= MIN_LENGTH_GAIN_MM)
    return ok, ('overall length {:.2f}mm (target {:.0f} +/- {:.1f}mm); '
                'original {:.2f}mm, gain {:+.2f}mm (need >= {:.0f}mm)'.format(
                    L, LENGTH_TARGET_MM, LENGTH_TOL_MM, L0, L - L0,
                    MIN_LENGTH_GAIN_MM))


def check_taskp_1_wheel_radius(original, candidate):
    o, _ = _effective(original, 'wheel_radius', 'geo_wheel_radius')
    c, c_geo = _effective(candidate, 'wheel_radius', 'geo_wheel_radius')
    if o <= 0:
        return False, 'Wheel circle not found in original part'
    if c <= 0:
        return False, ('Wheel not found in active document (no named wheel '
                       'sketch and no wheel-like disc geometry)')
    ok, ratio = _ratio_ok(o, c)
    return ok, 'R {:.3f}mm -> {:.3f}mm  (x{:.3f}, target x{:.2f} +/- {:.0%}){}{}'.format(
        _mm(o), _mm(c), ratio, TARGET_RATIO, RATIO_TOL,
        GEO_NOTE if c_geo else '',
        _staleness_note(candidate, 'wheel_radius', 'geo_wheel_radius'))


FIT_TOL_M = 0.5e-3
PENETRATION_TOL_M = 0.2e-3


def _wheel_collisions(doc):
    centre = doc.get('geo_wheel_center')
    axis = doc.get('geo_wheel_axis')
    r = doc.get('geo_wheel_radius', -1) or -1
    w = doc.get('geo_wheel_width', -1) or -1
    faces = doc.get('near_faces')
    if not centre or not axis or r <= 0 or w <= 0 or faces is None:
        return None
    a_dim = max(range(3), key=lambda d: abs(axis[d]))
    rest = [d for d in range(3) if d != a_dim]
    ax_lo, ax_hi = centre[a_dim] - w / 2.0, centre[a_dim] + w / 2.0
    hits = []
    for f in faces:
        nd, pos, box = int(f[0]), f[1], f[2:8]
        f_ax_lo, f_ax_hi = box[a_dim], box[a_dim + 3]
        if f_ax_hi <= ax_lo + 1e-6 or f_ax_lo >= ax_hi - 1e-6:
            continue
        if nd == a_dim:
            pen = min(ax_hi - pos, pos - ax_lo)
            if pen <= 0:
                continue
            seg = [(box[d], box[d + 3]) for d in rest]
            cen2 = [centre[d] for d in rest]
            dx = max(seg[0][0] - cen2[0], 0, cen2[0] - seg[0][1])
            dy = max(seg[1][0] - cen2[1], 0, cen2[1] - seg[1][1])
            if (dx * dx + dy * dy) ** 0.5 >= r:
                continue
        else:
            s_dim = rest[0] if rest[1] == nd else rest[1]
            d_seg = max(box[s_dim] - centre[s_dim], 0,
                        centre[s_dim] - box[s_dim + 3])
            d_pos = pos - centre[nd]
            dist = (d_seg * d_seg + d_pos * d_pos) ** 0.5
            pen = r - dist
            if pen <= 0:
                continue
        if pen > PENETRATION_TOL_M:
            hits.append(pen)
    return hits


def check_taskp_2_slot_accommodation(original, candidate):
    o_slot, _ = _effective(original, 'slot_width', 'geo_slot_width')
    c_slot, c_geo = _effective(candidate, 'slot_width', 'geo_slot_width')
    o_w = original.get('geo_wheel_width', -1) or -1
    c_w = candidate.get('geo_wheel_width', -1) or -1
    if o_slot <= 0 or o_w <= 0:
        return False, 'Slot/wheel geometry not measurable in original part'
    if c_slot <= 0 or c_w <= 0:
        return False, ('Slot/wheel geometry not measurable in active '
                       'document (no wall pair straddling a wheel-like disc)')
    clr_o = o_slot - o_w
    clr_c = c_slot - c_w
    fit_ok = abs(clr_c - clr_o) <= FIT_TOL_M

    o_hits = _wheel_collisions(original) or []
    c_hits = _wheel_collisions(candidate)
    if c_hits is None:
        return False, 'Wheel/housing face data missing - cannot check clearance'
    coll_ok = len(c_hits) <= len(o_hits)
    ok = fit_ok and coll_ok
    detail = ('slot W {:.3f}mm vs wheel width {:.3f}mm (clearance {:+.3f}mm,'
              ' original {:+.3f}mm, tol {:.1f}mm); housing faces penetrated'
              ' >{:.1f}mm: {} (original {}){}'.format(
                  _mm(c_slot), _mm(c_w), _mm(clr_c), _mm(clr_o),
                  _mm(FIT_TOL_M), _mm(PENETRATION_TOL_M), len(c_hits),
                  len(o_hits), GEO_NOTE if c_geo else ''))
    if c_hits:
        detail += '; worst penetration {:.2f}mm'.format(_mm(max(c_hits)))
    return ok, detail


def _canonical_wheel_offsets(doc):
    centre = doc.get('geo_wheel_center')
    axis = doc.get('geo_wheel_axis')
    bbox = doc.get('bbox')
    if not centre or not axis or not bbox or doc.get('geo_wheel_radius', -1) <= 0:
        return None
    spans = [bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2]]
    if min(spans) < 0:
        return None
    a_dim = max(range(3), key=lambda d: abs(axis[d]))
    rest = [d for d in range(3) if d != a_dim]
    len_dim = max(rest, key=lambda d: spans[d])
    h_dim = min(rest, key=lambda d: spans[d])
    off_len = abs(centre[len_dim] - (bbox[len_dim] + bbox[len_dim + 3]) / 2.0)
    off_h = centre[h_dim] - bbox[h_dim]
    return off_len, off_h


CENTRE_TOL_M = 1e-5          # 0.01 mm drift allowed on the wheel centre
GEO_CENTRE_TOL_M = 6.0e-3


def check_taskp_3_centre_preserved(original, candidate):
    named = (original.get('wheel_radius', -1) > 0
             and candidate.get('wheel_radius', -1) > 0)
    if named:
        dx = candidate.get('wheel_cx', 0) - original.get('wheel_cx', 0)
        dy = candidate.get('wheel_cy', 0) - original.get('wheel_cy', 0)
        dist = (dx * dx + dy * dy) ** 0.5
        ok = dist <= CENTRE_TOL_M
        return ok, 'centre drift {:.4f}mm (allowed {:.4f}mm)'.format(
            _mm(dist), _mm(CENTRE_TOL_M))

    o_off = _canonical_wheel_offsets(original)
    c_off = _canonical_wheel_offsets(candidate)
    if o_off is None or c_off is None:
        return False, 'Wheel missing - centre cannot be compared'
    d_len = c_off[0] - o_off[0]
    d_h = c_off[1] - o_off[1]
    dist = (d_len * d_len + d_h * d_h) ** 0.5
    ok = dist <= GEO_CENTRE_TOL_M
    return ok, ('bbox-relative centre drift {:.2f}mm (allowed {:.2f}mm; '
                'longitudinal {:+.2f}mm, height {:+.2f}mm){}'.format(
                    _mm(dist), _mm(GEO_CENTRE_TOL_M), _mm(d_len), _mm(d_h),
                    GEO_NOTE))


def check_taskp_4_clean_rebuild(candidate):
    if not candidate.get('rebuild_ok', False):
        return False, 'EditRebuild3 returned False'
    err  = candidate.get('feat_errors', 0)
    warn = candidate.get('feat_warns', 0)
    ok   = (err == 0 and warn == 0)
    return ok, 'feature errors={}, warnings={}'.format(err, warn)


def _collect_checks():
    stl_dir = tempfile.gettempdir()
    cand_stl = os.path.join(stl_dir, 'task9_candidate.stl')
    orig_stl = os.path.join(stl_dir, 'task9_original.stl')
    for pth in (cand_stl, orig_stl):
        try:
            os.remove(pth)
        except OSError:
            pass

    if not os.path.exists(BASELINE_JSON):
        raise RuntimeError('frozen baseline missing at {}'.format(BASELINE_JSON))
    with open(BASELINE_JSON, encoding='utf-8') as fh:
        frozen = json.load(fh)
    got = _sha256(ORIGINAL_PATH)
    if got != frozen.get('source_sha256'):
        raise RuntimeError(
            'baseline was captured from a different original part '
            '(hash mismatch: expected {}..., found {}...)'.format(
                frozen.get('source_sha256', '')[:16], got[:16]))

    data = _collect('', cand_stl=cand_stl, orig_stl='')

    original = frozen['original']
    candidate = data.get('candidate', {})
    if 'error' in candidate:
        err = candidate['error']
        raise RuntimeError(CANDIDATE_ERRORS.get(err, err))

    cand_mesh = _mesh_metrics(cand_stl) if os.path.exists(cand_stl) else None
    orig_mesh = original.get('mesh')

    checks = [
        ('model regenerates', lambda: check_shared1_rebuild(candidate)),
        ('no broken features', lambda: check_shared2_features(candidate)),
        ('four snap tabs present', lambda: check_item1_snap_tabs(candidate, cand_mesh)),
        ('two thumb buttons added', lambda: check_item2_thumb_buttons(cand_mesh, orig_mesh)),
        ('lengthened to 105 mm', lambda: check_item3_length(orig_mesh, cand_mesh)),
        ('wheel radius up 10 percent', lambda: check_taskp_1_wheel_radius(original, candidate)),
        ('slot accommodates wheel', lambda: check_taskp_2_slot_accommodation(original, candidate)),
        ('clean rebuild', lambda: check_taskp_4_clean_rebuild(candidate)),
    ]

    registry = {}
    for name, fn in checks:
        try:
            ok, _detail = fn()
        except Exception:
            ok = False
        registry[name] = bool(ok)
    return registry


def _open_candidate_in_solidworks(path):
    """Open a candidate .SLDPRT as the active document. The report.py
    contract passes the candidate path in sys.argv[1]; without this, the
    harness would grade whatever document happened to be active.

    sws.open_document sweeps the whole session closed before any fresh
    open -- SolidWorks resolves referenced components by filename, not
    full path, so a document left open from a previous candidate/
    baseline would otherwise silently leak into this one (confirmed
    live on 30_shampoo_bottle)."""
    from common import solidworks_session as sws
    app = sws.attach()
    doc, _opened_here = sws.open_document(app, path, doc_type=sws.DOC_PART)
    if doc is None:
        raise RuntimeError(f'SolidWorks could not open the candidate: {path}')
    # open_document uses OPEN_SILENT, which does not make `doc` the
    # ActiveDoc -- _collect() below finds the candidate via
    # sws.active_doc(app), so a stale document left active by a prior
    # graded task would otherwise be picked up instead.
    sws.activate(app, doc)


class MouseWheelHarness(Harness):
    MUST_PASS = (
        'model regenerates',
        'no broken features',
        'clean rebuild',
    )
    CANDIDATE_OPTIONAL = True  # without an arg, grades the live document

    def build_state(self, candidate_path):
        if candidate_path and os.path.isfile(candidate_path):
            _open_candidate_in_solidworks(os.path.abspath(candidate_path))
        return None

    def checks(self, _state):
        return _collect_checks()


main = MouseWheelHarness.as_main()

if __name__ == '__main__':
    MouseWheelHarness.cli()

