"""PROMPT（2026-10-31）：W7——请写作模型（abliteration，关推理）按人物表风格补全陈宇的服装字段。系统只给请求原文与格式，
内容由写作模型决定。产出写入 staging 新稿片段 data/staging_v3/为他而骚_ep02_陈宇造型补全_W7_20261031.md（标“待导入”），
并存 data/ab/prompt_v2/ep02/writer_revisions/w7_chen_yu.json。
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
STAGE = ROOT / "data" / "staging_v3" / "为他而骚_ep02_陈宇造型补全_W7_20261031.md"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cur = (ROOT / "data/staging_v3/为他而骚_ep02_补全候选_PROMPTv2_20261031.md").read_text(encoding="utf-8")
    looks = "\n".join(ln for ln in cur.splitlines() if ln.startswith("**造型｜") or re.match(r"^\| (林晚|顾沉|陈宇) \|", ln))
    req = (ROOT / "docs/ep02_iter/writer_requests.md").read_text(encoding="utf-8")
    w7 = req[req.index("## W7"):].split("\n## ")[0]
    user = f"""以下是总调度转来的写作请求 W7（原文）：
{w7}

技术原因：角色设定图按造型行逐件出图；“休闲装”这类笼统描述会被设定图模板的默认人台服装填满（CONSIST 两个 seed 都失败）。

当前 ep02 的造型行与人物表（照抄格式，林晚、顾沉作为风格参照）：
{looks}

请按第 2P 节造型格式，给陈宇写一行完整的 ep02 造型（服装 / 鞋 / 妆 / 发 / 甲 / 饰品 / EN 都写具体：款式 + 颜色 + 材质，粒度如“浅灰圆领卫衣”），
再写一句体型补充（是否补身高）和一句其他集是否换装的说明。输出格式（只输出这些）：
**造型｜陈宇**：服装=…｜鞋=…｜妆=…｜发=…｜甲=…｜饰品=…｜EN=…
体型=…
换装=…
"""
    ledger = json.loads((RW.OUT / "ledger.json").read_text(encoding="utf-8")) if (RW.OUT / "ledger.json").exists() else []
    from ns_api import script_chat as SC
    system, _ = SC.build_system_prompt(SC.load_config(), context=None, appendix_budget=0)
    reply = RW.call(system, user, ledger, reasoning=False, max_tokens=4000)
    look = re.search(r"^\*\*造型｜陈宇\*\*：.+$", reply, re.M)
    body = re.search(r"^体型\s*[=＝]\s*(.+)$", reply, re.M)
    chg = re.search(r"^换装\s*[=＝]\s*(.+)$", reply, re.M)
    res = {"made": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "待导入", "look_line": look.group(0) if look else None,
           "body": body.group(1) if body else None, "wardrobe_change": chg.group(1) if chg else None, "raw": reply}
    (OUT / "w7_chen_yu.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    STAGE.write_text("<!-- W7 写作模型产出（PROMPT 2026-10-31，abliteration 关推理）；状态：待导入。只替换 ep02 陈宇造型行。 -->\n"
                     + (res["look_line"] or reply) + f"\n<!-- 体型：{res['body']}；换装：{res['wardrobe_change']} -->\n",
                     encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "raw"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
