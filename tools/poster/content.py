"""海报文案：中文取自 P0_brief / P1_storyline（节选，不改写；存 data/posters/<run>/content_zh.json），
英文走写作网关 prompt_rewrite（只发文字）。
用法：.venv/Scripts/python.exe tools/poster/content.py [run ...]  → data/posters/<run>/content.json"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import POSTERS, ROOT, poster_runs, write_json_atomic  # noqa: E402

sys.path.insert(0, str(ROOT / "services" / "api"))
from ns_api import llm_config as L  # noqa: E402

SYS = ("You translate Chinese short-drama marketing copy into natural English for a streaming poster. "
       "Translate faithfully, do not add facts. Keep it concise and elegant. Output JSON only, same keys as the input; "
       "'cast' is a list of [name, role] pairs: romanize names as Lin Wan, Gu Chen, Chen Yu, A-Lan; roles: Lead, Antagonist, Supporting. "
       "Title: keep the meaning, e.g. 'Beneath the Patent Leather: Ten Days' style; Season Two as 'Season 2'.")


def main(argv=None):
    runs = (argv if argv is not None else sys.argv[1:]) or poster_runs()
    rv = L.resolve("prompt_rewrite")
    for run in runs:
        zh = json.loads((POSTERS / run / "content_zh.json").read_text(encoding="utf-8"))
        r = L.complete_text(rv, SYS, json.dumps(zh, ensure_ascii=False), 1500)
        txt = r["content"].strip()
        if txt.startswith("```"):
            txt = txt.split("\n", 1)[1].rsplit("```", 1)[0]
        out = {"zh": zh, "en": json.loads(txt),
               "source": f"data/pipeline/runs/{run}/P1_storyline.json premise; EN via prompt_rewrite {rv.get('name')}/{rv.get('model')}"}
        write_json_atomic(POSTERS / run / "content.json", out)
        print(run, json.dumps(out["en"], ensure_ascii=False))


if __name__ == "__main__":
    main()
