"""Video gates.

keyframe_gate  (PI-08 / PI-19)  first decoded frame vs the first keyframe, last decoded frame vs the last keyframe:
               size / aspect identity, PSNR, SSIM, CIEDE2000 of the centre-weighted mean colour over the first /
               last 0.5 s, and the whole-clip L* drift curve vs the first keyframe.
drift_gate     (PI-01 / PI-03 / PI-04)  frames every 0.5 s: SFace cosine to the reference face (median, 2 s window
               medians), hair HSV rule + hair ΔE vs the first sample, torso a/b-histogram Bhattacharyya and dominant
               colour ΔE vs the first sample.

Keyframes are compared after the same preparation H3 receives (centre-crop to the clip's aspect, Lanczos to the
clip size; gpu3 h3_keyframe). All numbers are technical; nothing here judges content.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import media as M
from .thresholds import judge

EDGE_S = 0.5
SAMPLE_STEP_S = 0.5
WINDOW_S = 2.0
SAME_PICTURE = 0.85  # ns_post.colormatch CcSettings.match_min: "keyframe must BE the clip's anchor"


def _aspect_diff(a: tuple[int, int], b: tuple[int, int]) -> float:
    ra, rb = a[0] / a[1], b[0] / b[1]
    return round(abs(ra - rb) / rb, 4)


def keyframe_gate(clip: Path, first_kf: Path | None, last_kf: Path | None, *, kf_provenance: dict | None = None,
                  info: dict | None = None, small: list[np.ndarray] | None = None) -> dict:
    info = info or M.video_info(clip)
    size = (info["width"], info["height"])
    res: list[dict] = [judge("Q-K1", list(size),
                             detail=f"video {size[0]}×{size[1]} @ {info['fps']:.3g} fps, {info['frames']} frames")]
    small = small if small is not None else M.decode_small(clip, info=info)
    n_edge = max(1, int(round(EDGE_S * info["fps"])))
    out = {"clip": str(clip), "video": info, "keyframes": kf_provenance or {}, "gates": res}
    frames = M.decode_indices(clip, [0], info)
    f0 = frames.get(0)
    fl = M.last_frame(clip, info)
    lab_small = [M.weighted_lab_mean(f) for f in small]

    for which, kf, frame, edge in (("first", first_kf, f0, lab_small[:n_edge]),
                                   ("last", last_kf, fl, lab_small[-n_edge:])):
        if kf is None or not Path(kf).is_file():
            why = f"no {which} keyframe available locally"
            if which == "first":
                res.append(judge("Q-K2", None, unchecked=why))
            else:
                res.append(judge("Q-K3", None, unchecked=why + " (shot has no independent last keyframe, or it "
                                                               "was not synced — PI-08)"))
            res.append(judge("Q-K4", None, unchecked=why, edge=which))
            continue
        raw = M.load_rgb(Path(kf))
        kf_size = (raw.shape[1], raw.shape[0])
        ad = _aspect_diff(kf_size, size)
        res.append(judge("Q-K1b", ad, detail=f"{which} keyframe {kf_size[0]}×{kf_size[1]} vs video "
                                             f"{size[0]}×{size[1]}", edge=which))
        prep = M.h3_geometry(raw, size)
        if frame is None:
            res.append(judge("Q-K2" if which == "first" else "Q-K3", None, unchecked=f"{which} frame not decoded"))
            continue
        p, s = M.psnr(frame, prep), M.ssim(frame, prep)
        if which == "first":
            res.append(judge("Q-K2", p, detail=f"SSIM {s}", ssim=s))
            res.append(judge("Q-K6", s, detail=f"PSNR {p} dB"))
        else:
            res.append(judge("Q-K3", s, detail=f"PSNR {p} dB", psnr=p))
        import cv2
        ref_lab = M.weighted_lab_mean(cv2.resize(prep, (small[0].shape[1], small[0].shape[0]),
                                                 interpolation=cv2.INTER_AREA))
        edge_mean = np.mean(edge, 0)
        de = round(M.de2000(edge_mean, ref_lab), 2)
        res.append(judge("Q-K4", de, edge=which, detail=f"{which} {EDGE_S}s mean LAB "
                         f"{[round(float(v), 1) for v in edge_mean]} vs keyframe {[round(float(v), 1) for v in ref_lab]}"))
        if which == "first":
            dl = [round(float(l[0] - ref_lab[0]), 2) for l in lab_small]
            out["dL_curve_1s"] = dl[::max(1, int(round(info["fps"])))]
            # only frames that still show the keyframe's picture (structure ≥ SAME_PICTURE): a camera move changes
            # L* through content, which is not colour drift
            kf_small = cv2.resize(prep, (small[0].shape[1], small[0].shape[0]), interpolation=cv2.INTER_AREA)
            same = [i for i, f in enumerate(small) if M.structure_match(f, kf_small) >= SAME_PICTURE]
            raw_i = int(np.argmax(np.abs(dl)))
            if same:
                wi = max(same, key=lambda i: abs(dl[i]))
                res.append(judge("Q-K5", round(abs(dl[wi]), 2), detail=(
                    f"max |ΔL*| over {len(same)}/{len(dl)} frames that structurally match the keyframe "
                    f"(≥{SAME_PICTURE}): frame {wi} ({wi / info['fps']:.2f} s) signed {dl[wi]}; all frames: "
                    f"{dl[raw_i]} at {raw_i / info['fps']:.2f} s"), frames_used=len(same)))
            else:
                res.append(judge("Q-K5", None, unchecked="no frame structurally matches the first keyframe"))
    return out


def _windows(times: list[float], vals: list[float | None], span: float) -> list[float]:
    meds = []
    for i, t0 in enumerate(times):
        w = [v for t, v in zip(times[i:], vals[i:]) if t - t0 <= span + 1e-6 and v is not None]
        if times[-1] - t0 + 1e-6 < span and meds:
            break
        if len(w) >= 2:
            meds.append(float(np.median(w)))
    return meds


def drift_gate(clip: Path, *, models=None, ref_embedding: np.ndarray | None = None, lead_expected: bool = True,
               back_view: bool = False, info: dict | None = None, step_s: float = SAMPLE_STEP_S) -> dict:
    import cv2
    from . import face as F
    info = info or M.video_info(clip)
    n = info["frames"]
    idx = sorted({min(n - 1, int(round(k * step_s * info["fps"]))) for k in range(int(info["duration"] / step_s) + 1)}
                 | {n - 1})
    frames = M.decode_indices(clip, idx, info)
    res: list[dict] = []
    rows = []
    for i in sorted(frames):
        rgb = frames[i]
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        row = {"frame": i, "t": round(i / info["fps"], 3)}
        face = None
        if models is not None:
            fs = [f for f in models.faces(bgr) if float(f[3]) >= F.MIN_FACE_PX]
            row["faces"] = len(fs)
            if fs:
                if ref_embedding is not None:
                    sims = [(F.cosine(models.embed(bgr, f), ref_embedding), f) for f in fs]
                    best = max(sims, key=lambda x: x[0])
                    row["sface"] = round(best[0], 3)
                    face = best[1]
                else:
                    face = F.largest(fs)
                row["face_px"] = round(float(face[3]), 1)
                row["emb"] = models.embed(bgr, face)
        if face is not None:
            row["hair"] = F.hair_colour(bgr, face)
            tb = F.torso_box(rgb.shape, face)
            row["torso_mode"] = "face-anchored" if tb else None
        else:
            tb = None
        row["_box"] = tb
        row["_rgb"] = rgb
        rows.append(row)

    out = {"clip": str(clip), "samples": len(rows), "step_s": step_s, "gates": res}
    # ---- identity ----
    if models is None:
        res.append(judge("Q-D1", None, unchecked="YuNet/SFace models not found (set NS_QC_VISION_DIR)"))
        res.append(judge("Q-D2", None, unchecked="YuNet/SFace models not found"))
    elif not lead_expected:
        res.append(judge("Q-D1", None, unchecked="林晚 not in the shot's visible characters"))
        res.append(judge("Q-D2", None, unchecked="林晚 not in the shot's visible characters"))
    elif back_view:
        res.append(judge("Q-D1", None, unchecked="back view in the script (gpu3 BACK_VIEW rule): identity not scored"))
        res.append(judge("Q-D2", None, unchecked="back view"))
    elif ref_embedding is None:
        res.append(judge("Q-D1", None, unchecked="no reference face embedding (config/face_reference.json)"))
        res.append(judge("Q-D2", None, unchecked="no reference face embedding"))
    else:
        per = [r.get("sface") for r in rows]
        got = [v for v in per if v is not None]
        miss = sum(1 for v in per if v is None)
        if len(got) < 2:
            res.append(judge("Q-D1", None, unchecked=f"only {len(got)} sampled frame(s) with a face ≥{F.MIN_FACE_PX}px"))
            res.append(judge("Q-D2", None, unchecked="fewer than 2 faces"))
        else:
            med = round(float(np.median(got)), 3)
            res.append(judge("Q-D1", med, detail=f"{len(got)}/{len(per)} samples with a face; min {min(got):.3f}; "
                                                 f"no-face samples {miss}", samples=per))
            wins = _windows([r["t"] for r in rows], per, WINDOW_S)
            res.append(judge("Q-D2", round(min(wins), 3) if wins else None,
                             detail="median per 2 s window (4 samples), minimum over windows",
                             unchecked=None if wins else "no 2 s window with ≥2 faces"))
        firsts = [r for r in rows if "emb" in r]
        if firsts:
            e0 = firsts[0]["emb"]
            out["self_similarity_to_first_face"] = [round(F.cosine(r["emb"], e0), 3) if "emb" in r else None
                                                    for r in rows]
    # ---- hair ----
    hairs = [(r["t"], r.get("hair")) for r in rows if r.get("hair") is not None]
    if not lead_expected or back_view:
        res.append(judge("Q-D3", None, unchecked="林晚 face not expected (cast / back view)"))
        res.append(judge("Q-D4", None, unchecked="林晚 face not expected"))
    elif not hairs:
        res.append(judge("Q-D3", None, unchecked="no face ≥60 px in the samples (hair band is anchored to the face)"))
        res.append(judge("Q-D4", None, unchecked="no face"))
    else:
        bad = [t for t, h in hairs if not h.get("ok")]
        res.append(judge("Q-D3", len(bad), detail=f"{len(bad)}/{len(hairs)} sampled frames fail the S3-F3 HSV rule"
                                                  + (f" at t={bad}" if bad else ""),
                         hair=[{"t": t, **{k: h.get(k) for k in ('ok', 'hue', 'value', 'blue_share', 'why')}}
                               for t, h in hairs]))
        lab0 = hairs[0][1]["lab"]
        des = [round(M.de2000(h["lab"], lab0), 2) for _, h in hairs]
        res.append(judge("Q-D4", max(des), detail=f"hair-band LAB ΔE2000 vs first sample (t={hairs[0][0]}s); per "
                                                  f"sample {des}"))
    # ---- torso / clothing ----
    anchored = [r for r in rows if r["_box"] is not None]
    if len(anchored) >= 2:
        mode, use = "face-anchored torso box", anchored
    else:
        mode = "centre box (no face to anchor)"
        use = rows
        for r in use:
            r["_box"] = F.centre_box(r["_rgb"].shape)
    if len(use) >= 2:
        h0 = F.ab_hist(use[0]["_rgb"], use[0]["_box"])
        d0 = F.dominant_lab(use[0]["_rgb"], use[0]["_box"])
        bh = [round(F.bhattacharyya(h0, F.ab_hist(r["_rgb"], r["_box"])), 3) for r in use]
        dd = [round(M.de2000(F.dominant_lab(r["_rgb"], r["_box"]), d0), 2) for r in use]
        wi = int(np.argmax(bh))
        res.append(judge("Q-D5", max(bh), detail=f"{mode}; worst at t={use[wi]['t']}s; {len(use)} samples",
                         per_sample=bh, mode=mode))
        res.append(judge("Q-D6", max(dd), detail=f"{mode}; dominant LAB ΔE2000 vs first sample", per_sample=dd))
    else:
        res.append(judge("Q-D5", None, unchecked="fewer than 2 usable samples"))
    out["rows"] = [{k: v for k, v in r.items() if not k.startswith("_") and k != "emb" and k != "hair"}
                   for r in rows]
    return out
