"""PROMPT（2026-10-31）：把 docs/ep02_iter/writer_requests.md 里 W2 / W4 / W6 交给写作模型（abliteration，用途 script_write）。
W1 / W3 / W5 并在 rewrite_ep02.py 的 H3 重写里处理。系统不写不评内容：只给请求原文 + 技术原因，收回写作模型的修订字段。
W4 / W6 涉及独白（台词）改动 → 只收“建议版本”，标“待项目方确认”，不替换生产数据。
输出：data/ab/prompt_v2/ep02/writer_revisions/（revisions.md 原文、revisions.json、ledger 并入上级 ledger.json）
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "prompt_v2"))
import rewrite_ep02 as RW  # noqa: E402

OUT = RW.OUT / "writer_revisions"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    d = json.loads((ROOT / "data/import/script_v2.json").read_text(encoding="utf-8"))
    g = d["globals"]
    specs = {s.id: s for s in RW.load_specs()}
    s8, s11 = specs["ep02-S8"], specs["ep02-S11"]
    max8 = int(3.5 * (12.25 - 0.3))
    max11 = int(3.5 * (10.12 - 0.3))
    user = f"""以下是总调度转来的三条写作请求（docs/ep02_iter/writer_requests.md），请你作为写作方处理。系统只说明技术原因，内容由你决定。

## W2（img / motion 统一后缀）
请求原文：剧本 img 统一后缀里有“无字幕、无文字、无水印”。cfg=1 时，正向提示词里的否定词反而会把这些东西画出来（ep02 S5 视频出现了“冷”字）。系统后缀已经改成只写正面描述；剧本后缀是否改成正面写法（如“画面干净、纯净背景”）由写作方决定。
当前 motion_suffix：{g.get('motion_suffix')}
当前 image_suffix：{g.get('image_suffix')}

## W4 + W6（ep02 独白，项目方闸门：只给建议版本，待项目方确认）
W4 请求原文：S8 独白约 25.6 s，镜头只有 12.25 s。合成规则把溢出判为不通过，独白在本镜结尾截断。需要缩短独白或拆镜。
W6 项目方原话：“旁白的声音很难听，是一个老女人的声音，一个 Chinese 的女人。这是一部 fashion 的都市片，所以旁白的声音一定要更加年轻，语气和描写都要更好一点。”（“描写”这一半归写作方）
技术约束：🎙 独白字数（不计标点）≤ 3.5×(镜长−0.3)：S8 镜长 12.25 秒 → ≤ {max8} 字；S11 镜长 10.12 秒 → ≤ {max11} 字。剧情含义、人物关系不变。
S8 现独白：{s8.audio.voiceover.text if s8.audio.voiceover else ''}
S11 现独白：{s11.audio.voiceover.text if s11.audio.voiceover else ''}
S8 画面（motion）：{s8.motion.text}
S11 画面（motion）：{s11.motion.text}

## 输出格式（只输出这些）
### W2
motion_suffix=<修订后全文，或写 不改>
image_suffix=<修订后全文，或写 不改>
### W4W6
S8=<建议独白全文>
S8_拆镜方案=<如果你认为应拆镜而不是缩短，写一句拆法；否则写 不拆>
S11=<建议独白全文，或写 不改>
说明=<一句话，写你改了什么>
"""
    ledger = json.loads((RW.OUT / "ledger.json").read_text(encoding="utf-8")) if (RW.OUT / "ledger.json").exists() else []
    from ns_api import script_chat as SC
    system, _ = SC.build_system_prompt(SC.load_config(), context=None, appendix_budget=0)
    reply = RW.call(system, user, ledger)
    (OUT / "request.md").write_text(user, encoding="utf-8")
    (OUT / "revisions.md").write_text(reply, encoding="utf-8")
    kv = dict(re.findall(r"^(motion_suffix|image_suffix|S8|S8_拆镜方案|S11|说明)\s*=\s*(.+)$", reply, re.M))

    def n(t):
        return len(re.sub(r"[\s，。、！？…—“”‘’：；,.!?\-]", "", t or ""))
    res = {"made": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "待项目方确认（W4/W6 独白）；W2 待总调度采纳",
           "W2": {k: kv.get(k) for k in ("motion_suffix", "image_suffix")},
           "W4W6": {"S8": kv.get("S8"), "S8_chars": n(kv.get("S8")), "S8_max": max8, "S8_split": kv.get("S8_拆镜方案"),
                    "S11": kv.get("S11"), "S11_chars": n(kv.get("S11")), "S11_max": max11, "note": kv.get("说明")}}
    neg = [w for w in ("无", "不", "没", "别", "勿", "禁") if w in (kv.get("image_suffix") or "") + (kv.get("motion_suffix") or "")]
    res["W2"]["negation_chars_left"] = neg
    (OUT / "revisions.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
