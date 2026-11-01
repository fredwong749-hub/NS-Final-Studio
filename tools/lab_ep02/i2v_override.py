"""LAB：剧本 H3 提示词 → I2VA 发送版（ns_render.h3_video.i2v_prompt：对齐句换 I2VA 句 + 去掉 <d> 外引用 Picture 2 的分句）。
输出 JSON 字符串，供 video-jobs 的 prompt_override 用。用法：python tools/lab_ep02/i2v_override.py S6"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "render_router"))
from ns_render import h3_video as HV
c = json.loads((ROOT / f"data/renders/ep02/{sys.argv[1]}/compiled.json").read_text(encoding="utf-8"))
p, removed = HV.i2v_prompt(c["video_prompt"])
sys.stderr.write("removed: " + json.dumps(removed, ensure_ascii=False) + "\n")
print(json.dumps(p, ensure_ascii=False))
