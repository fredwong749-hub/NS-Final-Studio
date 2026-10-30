"""
S1 闸门记录（SOP）：data/import/s1_gate.json。只记录、不自动接受——g3 接受必须由项目方/协调用 --accept 写入原话。

    uv run python tools/s1_gate.py                          # 查看（含是否对当前剧本有效）
    uv run python tools/s1_gate.py --validator-errors 0     # 记录校验器错误数（对当前剧本）
    uv run python tools/s1_gate.py --accept "项目方原话…"    # 记录 G3 接受（对当前剧本）
    uv run python tools/s1_gate.py --revoke                 # 撤销接受

记录绑定当前 data/import/script_v2.json 的 sha256；剧本重新导入后自动失效（state_timeline 视为未通过）。
state_timeline 的 provisional = !(剧本 ≥ v3 且 validator_errors == 0 且 g3_accepted)。改完会重建时间线。
"""
import argparse
import json
import sys
import time

from ns_agent import state_timeline as T
from ns_agent.bible import _sha_json, project_root


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--accept", metavar="OWNER_QUOTE")
    ap.add_argument("--revoke", action="store_true")
    ap.add_argument("--validator-errors", type=int)
    ap.add_argument("--root")
    ap.add_argument("--no-rebuild", action="store_true")
    a = ap.parse_args(argv)
    root = project_root(a.root)
    p = root / T.S1_GATE
    script_path = root / "data" / "import" / "script_v2.json"
    if not script_path.is_file():          # 没有剧本：什么都不写（尤其不能写一条没绑定剧本的 G3 接受）
        print(f"没有剧本 {script_path}：先导入剧本再记录 S1 闸门", file=sys.stderr)
        return 2
    sha = _sha_json(script_path)            # 与 state_timeline / bible_version 同一规范化哈希（CRLF 不影响）
    try:
        gate = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        gate = {}
    if gate.get("script_sha") != sha:
        gate = {"script_sha": sha}          # 剧本变了：旧记录作废
    changed = False
    if a.accept is not None:
        if not a.accept.strip():
            print("--accept 必须写项目方原话/消息引用", file=sys.stderr)
            return 2
        gate.update(g3_accepted=True, g3_ref=a.accept.strip(), accepted_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        changed = True
    if a.revoke:
        gate.update(g3_accepted=False, g3_ref="", accepted_at=None)
        changed = True
    if a.validator_errors is not None:
        gate["validator_errors"] = a.validator_errors
        changed = True
    if changed:
        gate["checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        gate["script_sha"] = sha
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        if not a.no_rebuild:
            T.write(root)
    from ns_schema.script import ScriptImport
    script = ScriptImport.model_validate_json(script_path.read_text(encoding="utf-8"))
    eff = T.read_s1_gate(root, sha)
    ver = T.script_version(script)
    prov = not (T._ver_num(ver) >= 3 and eff["validator_errors"] == 0 and eff["g3_accepted"])
    print(json.dumps({"script": ver, "script_sha": sha, **eff, "provisional": prov}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
