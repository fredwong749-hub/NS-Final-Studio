"""GET /api/gpu3/rules 与 /rules/{rule_id}（子进程 shot_audit.py --explain，按 rule_id + 规则表 sha 缓存）。"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ns_canvas import rules as R
from ns_canvas.app import create_app
from ns_canvas.config import RootCfg, Settings

P = "/api/gpu3"
FAKE = r'''
import json, sys, time
from pathlib import Path
rid = sys.argv[sys.argv.index("--explain") + 1]
with open(Path(__file__).with_name("calls.txt"), "a") as f:
    f.write(rid + "\n")
if rid == "H3-A7":
    time.sleep(5)
if rid == "P-B1":
    print("not json"); sys.exit(1)
known = ["H3-A1", "H3-A5", "H3-A7", "P-B1"]
print(json.dumps({"found": rid in known, "rule_id": rid, "rule": "规则" + rid, "check": "c", "level": "block",
                  "sop_ref": "§9A.1", "sop_lines": [{"line": 1, "text": "t"}], "example_pass": "ok", "example_fail": "no",
                  "implementation": "ns_schema.h3_lint", "heuristic": False, "rules_version": "rule_ids/v1"}, ensure_ascii=False))
sys.exit(0 if rid in known else 2)
'''
TABLE = """# 逐镜审计规则编号表
> 版本：`rule_ids/v1`（2026-10-30）。
## H3-A 提示词结构
| rule_id | 规则 | 机器检查方法 | 级别 | SOP 出处 |
|---|---|---|---|---|
| H3-A1 | 对齐句 | 正则 | block | §9A.1 #1 |
| H3-A5 | 不写否定句 | 找 `\b(no|not|never)\b`、`n't` | block | §9A.1 #8 |
| H3-A7 | 英文正文 | CJK | block | §9A.1 #7 |
| H3-A9 | 只写看得见的（作废） | — | warn | §9A.1 #9 |
## P-B 帧
| rule_id | 规则 | 机器检查方法 | 级别 | SOP 出处 |
|---|---|---|---|---|
| P-B1 | 帧数 | 计算 | block | §6 |
"""


@pytest.fixture
def env(tmp_path: Path):
    R._cache.clear()
    scripts = tmp_path / "ns-studio" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "shot_audit.py").write_text(FAKE, encoding="utf-8")
    table = tmp_path / "rule_ids.md"
    table.write_text(TABLE, encoding="utf-8")
    base = tmp_path / "renders_gpu3"
    base.mkdir()
    s = Settings(queue_dir=base, roots=[RootCfg("renders_gpu3", "takes", base)], cache_dir=tmp_path / "c",
                 script_json=None, rule_ids=table, shot_audit=scripts / "shot_audit.py",
                 shot_audit_python=sys.executable, explain_timeout=2)
    return TestClient(create_app(s)), tmp_path, scripts / "calls.txt"


def test_list(env):
    c, _, _ = env
    d = c.get(f"{P}/rules").json()
    assert d["version"] == "rule_ids/v1" and d["count"] == 5 and len(d["rules_sha"]) == 64
    a5 = next(r for r in d["rules"] if r["rule_id"] == "H3-A5")
    assert a5 == {"rule_id": "H3-A5", "rule": "不写否定句", "check": "找 `\b(no|not|never)\b`、`n't`", "level": "block", "sop_ref": "§9A.1 #8",
                  "section": "H3-A 提示词结构", "retired": False}
    assert next(r for r in d["rules"] if r["rule_id"] == "H3-A9")["retired"] is True
    assert next(r for r in d["rules"] if r["rule_id"] == "P-B1")["section"] == "P-B 帧"


def test_explain_and_cache(env):
    c, tmp, calls = env
    r = c.get(f"{P}/rules/H3-A5")
    assert r.status_code == 200
    d = r.json()
    assert d["found"] and d["rule_id"] == "H3-A5" and d["example_fail"] == "no" and d["cached"] is False
    assert d["rules_sha"] == c.get(f"{P}/rules").json()["rules_sha"] and d["retired"] is False
    assert c.get(f"{P}/rules/H3-A5").json()["cached"] is True
    assert calls.read_text().splitlines() == ["H3-A5"]
    # 规则表一改（sha 变），缓存失效
    (tmp / "rule_ids.md").write_text(TABLE + "\n", encoding="utf-8")
    assert c.get(f"{P}/rules/H3-A5").json()["cached"] is False
    assert calls.read_text().splitlines() == ["H3-A5", "H3-A5"]


def test_errors(env):
    c, _, calls = env
    assert c.get(f"{P}/rules/NOPE-1").status_code == 404                 # 规则表里没有：不起子进程
    assert c.get(f"{P}/rules/bad id").status_code == 404
    assert not calls.exists()
    assert c.get(f"{P}/rules/H3-A9").status_code == 404                  # 表里有、脚本说 found:false
    assert c.get(f"{P}/rules/H3-A7").status_code == 504                  # 超时
    assert c.get(f"{P}/rules/P-B1").status_code == 502                   # 输出不是 JSON
