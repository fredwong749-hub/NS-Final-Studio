"""契约 Q9（出图）/ V9（视频）“本地看图复核”：把本地看图模型判定变成一条契约项。

只记录期（默认）：有缺陷 → status "na" + evidence.would_fail=True（与 postflight 的 record_only 口径一致）。
某检查项 config/vqa.json checks.<id>.blocking = true（总调度按标定 ≥0.85 批准后才改）→ 该项缺陷 = "fail"。
underage_look 从第一天起阻断（HC-07）。没有判定 / 服务不可用 = "untested"（不算通过）。

REFLOCK 在 postflight.evaluate 里加（一处）：
    from ns_agent.vqa import contract as VQ
    st, d, ev = VQ.q9(vlm)            # vlm = payload.get("vlm") 或 VQ.cached_for(image)
    add("Q9", st, d, **ev)            # TITLES["Q9"] = VQ.TITLE
VIDEO10 / evaluate_video 同理用 VQ.v9(score.get("vlm"))，VTITLES["V9"] = VQ.VTITLE。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import ROOT, cfg

TITLE = "本地看图复核（VLM，多手 / 鞋 / 造型 / 身份 / 多人 / 场景 / 文字 / 看镜头 / 塑料感 / 坏块 / 低清）"
VTITLE = "本地看图复核（VLM 抽帧：片内一致 / 变形 / 开头盯镜头 + 出图各项）"
INDEX = ROOT / "data" / "vqa" / "index.json"     # 图片相对路径 → 判定缓存键（client 写）


def _all_checks() -> dict:
    c = cfg()
    return {**(c.get("checks") or {}), **(c.get("video_checks") or {})}


def _fmt(ids: list[str], v: dict) -> str:
    zh = {k: x.get("zh", k) for k, x in _all_checks().items()}
    return "；".join(f"{zh.get(i, i)}：{(v.get('checks') or {}).get(i, {}).get('e', '')}".rstrip("：") for i in ids)


def gate_cfg() -> dict:
    """config/vqa.json gate（VQAGATE 11-01，项目方原话转阻断，D-VQA-01）"""
    return cfg().get("gate") or {}


def enforced() -> bool:
    return bool(gate_cfg().get("enforce")) and bool((cfg().get("judge") or {}).get("enforce"))


def _item(v: dict | None, video: bool) -> tuple[str, str, dict]:
    if not v:
        return "untested", "没有本地看图复核结果（服务排队 / 未跑）", {}
    if v.get("error"):
        return "untested", f"本地看图复核失败：{v['error']}", {"key": v.get("key")}
    checks = _all_checks()
    defects = [d for d in v.get("defects") or [] if d in checks]
    # 只有 defect（高置信度）且该项 blocking 才拦；unsure = 低置信度只记录。enforce 关掉时只有 underage_look 拦（HC-07）
    blocking = [d for d in defects if (checks[d] or {}).get("blocking") and (enforced() or d == "underage_look")]
    record = [d for d in defects if d not in blocking]
    ev = {"defects": defects, "unsure": v.get("unsure") or [], "key": v.get("key"), "model": v.get("model"),
          "maps_to": {d: checks[d].get("video" if video and "video" in checks[d] else "contract") for d in defects},
          "record_only": bool(record and not blocking)}
    if blocking:
        return "fail", _fmt(blocking, v) + ("；另有只记录项：" + _fmt(record, v) if record else ""), ev
    if record:
        ev["would_fail"] = True
        return "na", "只记录（不阻断，待标定）：" + _fmt(record, v), ev
    return "pass", "本地看图模型未报缺陷" + (f"（拿不准：{'、'.join(ev['unsure'])}）" if ev["unsure"] else ""), ev


def q9(v: dict | None) -> tuple[str, str, dict]:
    return _item(v, False)


def v9(v: dict | None) -> tuple[str, str, dict]:
    return _item(v, True)


def cached_for(image: str | Path) -> dict | None:
    """postflight 拿不到 payload["vlm"] 时：按图片路径查 data/vqa/index.json → data/vqa/verdicts/<key>.parsed.json"""
    try:
        idx = json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    p = str(image).replace("\\", "/")
    rel = p.split("NS-Final Studio/", 1)[-1]
    key = idx.get(rel) or idx.get(p)
    f = ROOT / "data" / "vqa" / "verdicts" / f"{key}.parsed.json" if key else None
    if f and f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return None


def remember(image: str | Path, verdict: dict) -> None:
    """把判定写进索引（client 调用后由调用方存）"""
    if not verdict.get("key"):
        return
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    try:
        idx = json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        idx = {}
    rel = str(image).replace("\\", "/").split("NS-Final Studio/", 1)[-1]
    idx[rel] = verdict["key"]
    INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=0), encoding="utf-8")
    (ROOT / "data" / "vqa" / "verdicts" / f"{verdict['key']}.parsed.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- VQAGATE：出图闸门（接在 PRODUCER _postflight / gate_scan 上）
def inspect_for(sid: str, kind: str, image: str | Path, prompt: str, references: list[str] | None, **kw) -> dict:
    """本地看图（带跨镜连贯参考）→ 判定；写 index 供 cached_for 查。kind = first | last"""
    from . import client
    from . import continuity as CT
    extra, note = CT.refs_for(sid, kind)
    me = str(Path(image).resolve())
    extra = [(f, lab) for f, lab in extra if str(Path(f).resolve()) != me]
    v = client.inspect_image(str(image), prompt or "", list(references or []), extra_refs=extra,
                             spec={"continuity": note} if note else None, **kw)
    v["continuity_ref"] = [f for f, _ in extra]
    if not v.get("error"):
        merge_gaze(v, gaze_mp(image), prompt or "")
    remember(image, v)
    return v


def gaze_mp(image: str | Path) -> list[dict] | None:
    """看镜头旁证（同一套 Q9 的 eye_contact，不另起检测器）：MediaPipe 虹膜（packages/qc/ns_qc/gaze_mp.py），
    YuNet 框裁切放大跑小脸。只在装了 mediapipe 的项目 .venv 里有；没有 → None"""
    try:
        import sys
        qc = str(ROOT / "packages" / "qc")
        if qc not in sys.path:
            sys.path.insert(0, qc)
        import cv2
        from ns_qc import gaze as GZ
        from ns_qc import gaze_mp as GM
        bgr = cv2.imread(str(image))
        if bgr is None or GM.landmarker() is None:
            return None
        m = GZ._models()
        boxes = [tuple(float(x) for x in f[:4]) for f in (m.faces(bgr) if m else [])]
        out = []
        for b in boxes:
            if b[3] < 0.03 * bgr.shape[0]:
                continue
            f = GM.face_in_box(bgr, b)
            if f:
                out.append(f)
        return out if boxes else (GM.faces(bgr) or [])
    except Exception:  # noqa: BLE001
        return None


_NEG_EYE = ("非看镜头", "不是看镜头", "未看镜头", "没有看镜头", "没看镜头", "不看镜头", "均未看", "都没有看", "无人看镜头", "没有人看镜头")


_NEG_LIMB = ("各5指", "各 5 指", "被遮挡", "遮挡", "数量正常", "无多余", "没有多余", "未见多余", "正常")


def sanitize(v: dict) -> None:
    """自相矛盾的 defect 降成 unsure：多肢 / 手指（ep02-S8：判 extra_limbs defect、证据却写“双手各5指，但左手小指被遮挡”）"""
    for k in ("extra_limbs", "hand_malformed"):
        c = (v.get("checks") or {}).get(k) or {}
        e = str(c.get("e") or "")
        if c.get("s") == "defect" and any(n in e for n in _NEG_LIMB) and not re.search(r"(多|三|3)\s*只手|多出|第三只|多一只", e):
            c.update(s="unsure", e=f"（自相矛盾，降为拿不准）{e}"[:300])
            v["defects"] = [d for d in v.get("defects") or [] if d != k]
            v["unsure"] = sorted(set(v.get("unsure") or []) | {k})
    _sanitize_eye(v)


def _sanitize_eye(v: dict) -> None:
    """看图模型自相矛盾的 eye_contact defect（ep03-S4：判 defect、证据却写“两人均未看镜头”；people[].gaze 也没有“看镜头”）
    → 降成 unsure（低置信度，不挡）。gaze_mp 高置信度命中会在 merge_gaze 里重新记 defect"""
    c = (v.get("checks") or {}).get("eye_contact") or {}
    if c.get("s") != "defect":
        return
    e = str(c.get("e") or "")
    looks = any("镜头" in str((p or {}).get("gaze") or "") and not any(n in str((p or {}).get("gaze")) for n in ("不", "未", "没"))
                for p in v.get("people") or [] if isinstance(p, dict))
    if any(n in e for n in _NEG_EYE) or (v.get("people") and not looks and not any(k in e for k in ("直视", "正对镜头", "盯", "看向镜头", "看镜头"))):
        c.update(s="unsure", e=f"（自相矛盾，降为拿不准）{e}"[:300])
        v["defects"] = [d for d in v.get("defects") or [] if d != "eye_contact"]
        v["unsure"] = sorted(set(v.get("unsure") or []) | {"eye_contact"})


def refresh_gaze(v: dict, image, prompt: str) -> None:
    """旧判定里 gaze_mp 记的 eye_contact 按现行阈值重算（阈值改过时用）：先还原看图模型原判，再重跑 merge_gaze"""
    c = (v.get("checks") or {}).get("eye_contact") or {}
    if str(c.get("e") or "").startswith("gaze_mp"):
        m = re.search(r"看图模型原判 (\w+)", c["e"])
        orig = m.group(1) if m else "ok"
        v["checks"]["eye_contact"] = {"s": orig, "e": ""}
        v["defects"] = [d for d in v.get("defects") or [] if d != "eye_contact"] + (["eye_contact"] if orig == "defect" else [])
        v.pop("gaze_mp", None)
    if "gaze_mp" not in v:
        merge_gaze(v, gaze_mp(image), prompt)
    else:
        sanitize(v)


def merge_gaze(v: dict, faces: list[dict] | None, prompt: str) -> None:
    """高置信度看镜头（config gate.gaze_mp：|A×yaw + eye_x| ≤ T 且 pitch ≤ P，标定见 docs/vqa/GATE_CALIBRATION.md）
    且原文没写看镜头 → 把 eye_contact 记成 defect（证据注明 gaze_mp）。VLM 已判 defect 的不动"""
    sanitize(v)
    g = gate_cfg().get("gaze_mp") or {}
    if faces is None or not g.get("enabled", True):
        return
    from . import rubric
    A, T, P = float(g.get("A", 0.3)), float(g.get("T", 0.05)), float(g.get("P", 0.12))
    D, BL = float(g.get("down_max", 0.35)), float(g.get("blink_max", 0.6))
    # 垂眼 / 闭眼排除（总调度 18:4x：ep04-S2 林晚垂眼看碗，眼睑下垂被当成正视）：blendshape eyeLookDown（bs_y）> D 或 eyeBlink > BL 不算
    hits = [f for f in faces if abs(A * f["yaw_n"] + f["eye_x"]) <= T and f["pitch_n"] <= P
            and f.get("bs_y", 0) <= D and f.get("blink", 0) <= BL]
    v["gaze_mp"] = {"faces": [{k: f.get(k) for k in ("yaw_n", "pitch_n", "eye_x", "gaze_x", "bs_y", "blink")} for f in faces][:4],
                    "hits": len(hits)}
    if not hits or rubric.spec_from_prompt(prompt).get("camera_ok") == "允许":
        return
    c = v.setdefault("checks", {})
    if (c.get("eye_contact") or {}).get("s") != "defect":
        c["eye_contact"] = {"s": "defect", "e": f"gaze_mp 虹膜测得 {len(hits)} 张脸正对镜头（|{A}×yaw+eye_x|≤{T}）"
                                                + (f"；看图模型原判 {c['eye_contact']['s']}" if c.get("eye_contact") else "")}
        v["defects"] = sorted(set(v.get("defects") or []) | {"eye_contact"})
        v["unsure"] = [u for u in v.get("unsure") or [] if u != "eye_contact"]


def apply(pf: dict, v: dict | None) -> dict:
    """把看图判定并进契约结果：替换 / 加上 Q9 项，按 enforce 重算 ok / blocking / reasons。原地改并返回 pf"""
    st, d, ev = q9(v)
    if st == "untested" and not (enforced() and gate_cfg().get("untested_blocks", True)):
        st, d = "na", "只记录（没有本地看图结果）：" + d
    items = [i for i in pf.get("items") or [] if i.get("id") != "Q9"]
    items.append({"id": "Q9", "title": TITLE, "status": st, "detail": d, "evidence": ev})
    pf["items"] = items
    blk = [b for b in (pf.get("blocking") or []) if b != "Q9"]
    if st in ("fail", "untested"):
        blk.append("Q9")
        pf["reasons"] = [r for r in pf.get("reasons") or [] if not str(r).startswith("Q9")] + [f"Q9 {d}"]
    pf["blocking"] = blk
    if pf.get("ok") is not None or st in ("fail", "untested"):
        pf["ok"] = bool(pf.get("ok")) and st not in ("fail", "untested")
    pf["vqa_gate"] = {"status": st, "defects": ev.get("defects") or [], "unsure": ev.get("unsure") or [],
                      "key": ev.get("key"), "enforce": enforced(), "continuity_ref": (v or {}).get("continuity_ref")}
    return pf


def q9_passed(pf: dict | None) -> bool:
    """build_jobs.passed_frames 用：视频只派“图片闸门通过”的首帧（gate.video_requires_q9）；没有看图结果 = 未通过"""
    if not (enforced() and gate_cfg().get("video_requires_q9", True)):
        return True
    it = next((i for i in (pf or {}).get("items") or [] if i.get("id") == "Q9"), None)
    return bool(it) and it.get("status") in ("pass", "na")


def ref_files(asset_refs: dict) -> list[str]:
    """asset_refs 记录（ns_agent.asset_refs.record）→ 参考图绝对路径（槽位顺序，去重）"""
    out = []
    for sl in (asset_refs or {}).get("slots") or []:
        f = sl.get("file") if isinstance(sl, dict) else None
        if not f:
            continue
        for c in (Path(f), ROOT / f, ROOT / "data" / f):
            if c.is_absolute() and c.exists():
                if str(c) not in out:
                    out.append(str(c))
                break
    return out
