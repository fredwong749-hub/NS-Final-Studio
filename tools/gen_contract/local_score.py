"""LOCALGPU（11-01，总调度 fredw-2b 派）：出图后契约的“远端”度量在笔记本本机算——断网时契约也能判全。

与 remote_score.postflight_full 同口径、同代码：
- Q1 身份 / Q3 景别 / Q6 文字：tools/series10_imggen/score_remote.py（insightface buffalo_l = retinaface det_10g + arcface w600k_r50，
  rapidocr-onnxruntime），在 D:\\ns_score\\venv 里跑（CPU），模型根 NS_IDM_ROOT = D:\\ns_score\\models\\insightface；
- Q5 坏手 / 多肢：tools/series10_imggen/hands_remote.py（mediapipe Tasks hand_landmarker + pose_landmarker_full，CPU），
  项目 .venv（mediapipe 1.2.0），模型 NS_MP_MODELS = D:\\ns_score\\models\\mediapipe；
- Q2 / Q4 / Q7（CLIP）：postflight.run 本来就在笔记本算（metrics.py，同一份代码）；
身份脸 = remote_score.local_faces（与出图同一张，asset_refs.face_of）。全部 CPU，不占显卡（不进轮流机制）。
用法：postflight_local([{id, file, request}]) → {id: postflight dict}；CLI：python tools/gen_contract/local_score.py <png> [<png>...]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMG = ROOT / "tools" / "series10_imggen"
SCORE_PY = Path(os.environ.get("NS_SCORE_PY", r"D:\ns_score\venv\Scripts\python.exe"))
HAND_PY = Path(os.environ.get("NS_HAND_PY", str(ROOT / ".venv" / "Scripts" / "python.exe")))
IDM_ROOT = os.environ.get("NS_IDM_ROOT", r"D:\ns_score\models\insightface")
MP_MODELS = os.environ.get("NS_MP_MODELS", r"D:\ns_score\models\mediapipe")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def available() -> bool:
    return SCORE_PY.exists() and HAND_PY.exists() and (Path(IDM_ROOT) / "models" / "buffalo_l" / "w600k_r50.onnx").exists() \
        and (Path(MP_MODELS) / "hand_landmarker.task").exists() and (Path(MP_MODELS) / "pose_landmarker_full.task").exists()


def _json_line(out: str) -> dict | None:
    ls = [ln for ln in (out or "").splitlines() if ln.startswith("{")]
    return json.loads(ls[-1]) if ls else None


def score(files: dict[str, str], timeout: float = 1200) -> dict:
    """{id: 本机 png} → {"items", "cross", "hands", "refs"}（= remote_score.score_local_files 的返回格式）"""
    sys.path.insert(0, str(ROOT / "tools" / "gen_contract"))
    import remote_score as RS
    refs = {cid: [str(ROOT / f)] for cid, f in RS.local_faces().items()}
    items = [{"id": k, "path": str(v)} for k, v in files.items()]
    env = dict(os.environ, NS_IDM_ROOT=IDM_ROOT, NS_MP_MODELS=MP_MODELS, PYTHONUTF8="1")
    r = subprocess.run([str(SCORE_PY), "-I", "-X", "utf8", str(IMG / "score_remote.py"), "-"], input=json.dumps({"refs": refs, "items": items}),
                       capture_output=True, text=True, timeout=timeout, env=env, encoding="utf-8", errors="replace",
                       creationflags=NO_WINDOW)
    s = _json_line(r.stdout)
    if not s:
        raise RuntimeError("本机 score_remote 失败：" + (r.stderr or "")[-400:])
    for it in s.get("items", {}).values():
        for f in it.get("faces", []):
            f.pop("emb", None)
    hi = [{"id": i["id"], "path": i["path"], "faces": len(s["items"].get(i["id"], {}).get("faces", []))} for i in items]
    rh = subprocess.run([str(HAND_PY), "-I", "-X", "utf8", str(IMG / "hands_remote.py")], input=json.dumps({"items": hi}), capture_output=True,
                        text=True, timeout=timeout, env=env, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    h = _json_line(rh.stdout)
    if h is None:
        raise RuntimeError("本机 hands_remote 失败：" + (rh.stderr or "")[-400:])
    return {"items": s.get("items", {}), "cross": s.get("cross", {}), "hands": h, "refs": list(refs)}


def postflight_local(jobs: list[dict]) -> dict:
    """jobs = [{"id", "file", "request"}] → {id: postflight dict}（Q1–Q8 全测；Q9 看图另走 vqa）"""
    for p in ("services/agent", "packages/schema", "services/render_router"):
        if str(ROOT / p) not in sys.path:
            sys.path.insert(0, str(ROOT / p))
    from ns_agent.gen_contract import postflight as PO
    m = score({j["id"]: j["file"] for j in jobs})
    out = {}
    for j in jobs:
        d = PO.run("image", {"image": str(j["file"]), "request": j.get("request") or {}, "remote": m["items"].get(j["id"]),
                             "cross": m.get("cross"), "hands": (m.get("hands") or {}).get(j["id"])})
        d.pop("local", None)
        d["measured_on"] = "laptop（本机 CPU：buffalo_l / rapidocr / mediapipe；CLIP 本机）"
        out[j["id"]] = d
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(score({Path(p).stem: p for p in sys.argv[1:]}), ensure_ascii=False)[:4000])
