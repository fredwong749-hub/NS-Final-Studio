"""V6 多手标定（VQAGATE 11-01，docs/vqa/V6_HANDCOUNT_PLAN.md）：本地看图数手（540×960 代理），正例 = 总调度点名的 ep01-S2 mot / S4 s2。→ data/vqa/gate_calib/v6_runs.json"""
import json, sys, time
sys.path.insert(0, r"D:\NS-Final Studio\services\agent")
from pathlib import Path
from ns_agent.vqa import client as VC
R = Path(r"D:\NS-Final Studio")
V = R / "data/pipeline/runs/series10_v1/video"
# 标签：总调度点名多手 = S2(mot)、S4(s2)；其余为已通过且没被点名手部问题的（弱反例）
items = [("ep01-S2", True, 1), ("ep01-S4", True, 2), ("ep01-S1", False, 1), ("ep01-S5", False, 1), ("ep01-S7", False, 1),
         ("ep04-S1", False, None), ("ep04-S2", False, None), ("ep04-S3", False, None), ("ep04-S5", False, None)]
rows = []
for sid, lab, ppl in items:
    clip = V / "episodes" / sid[:4] / f"{sid}.mp4"
    prompt = "数清每一帧里每个人的手：people[].hands_visible 按第几帧写进 e；多出的手写清第几帧哪个人"
    v = VC.inspect_video(str(clip), prompt, [], wait_s=1500, n=8)
    pc = v.get("people_count") or ppl or 1
    hands = sum(int((p or {}).get("hands_visible") or 0) for p in v.get("people") or [] if isinstance(p, dict))
    rows.append({"shot": sid, "label_multi_hand": lab, "error": v.get("error"), "defects": v.get("defects"),
                 "extra_limbs": (v.get("checks") or {}).get("extra_limbs"), "people_count": pc, "hands_frame1": hands,
                 "key": v.get("key")})
    print(rows[-1], flush=True)
    (R / "data/vqa/gate_calib/v6_runs.json").write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": "540×960 代理（本机只有代理）", "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
