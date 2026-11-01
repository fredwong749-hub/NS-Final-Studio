"""RECALL 2026-11-01：由 data/_quarantine_20261101/moves.jsonl 生成 MANIFEST.md（可重复运行）。"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"D:\NS-Final Studio")
Q = ROOT / "data" / "_quarantine_20261101"

# 已归档、可列入项目方最终删除的目录（大小为 2026-11-01 01:50 du 实测）
ARCHIVED = [
    ("data/renders/_archive_60ep_20261031", "1.6G", "60 集旧渲染（10-31 已归档）"),
    ("data/renders_gpu3/_archive_60ep_20261031", "约 50M", "60 集旧 gpu3 渲染记录（10-31 已归档）"),
    ("data/_archive/20261031", "2.5G", "10-31 第一轮清理归档（旧代码 / 旧剧本 / previews）"),
    ("data/_archive/20261031_r2", "591M", "10-31 第二轮清理归档"),
    ("data/import/backups/script_v2.20261030-220659.json", "612K", "60 集剧本备份（导入 series10 前）"),
    ("data/import/backups/script_v2.20261031-172058.json", "620K", "60 集剧本备份"),
    ("data/import/backups/script_v2.20261031-200848.json", "708K", "60 集剧本备份"),
    ("data/import/backups/script_v2.20261031-231559.json", "736K", "60 集剧本备份（series10 replace 导入前最后一份）"),
]


def human(n: int) -> str:
    for u in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}T"


def main():
    rows = [json.loads(l) for l in (Q / "moves.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    tot = defaultdict(int)
    cnt = defaultdict(int)
    out = ["# 隔离区清单（data/_quarantine_20261101）", "",
           "> RECALL 2026-11-01。只移动、不删除。项目方一键决定：“先隔离，验证后你删”。最终删除由项目方本人运行 `ops/cleanup/delete_quarantine_20261101.ps1`。",
           "> 恢复：把 dst 移回 src（笔记本：`Move-Item`；服务器：`mv`）。配置文件的原件在 `data/_quarantine_20261101/config/*.orig_20261101`。", "",
           "| # | 类别 | 机器 | 原路径 | 大小 | 状态 | 原因 |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        b = int(r.get("bytes") or 0)
        if r.get("status") in ("moved",):
            tot[(r["cat"], r.get("host", "laptop"))] += b
            cnt[(r["cat"], r.get("host", "laptop"))] += 1
        src = r["src"].replace(str(ROOT) + "\\", "")
        out.append(f"| {i} | {r['cat']} | {r.get('host','laptop')} | `{src}` | {human(b) if b else '-'} | {r.get('status')} | {r.get('reason','')} |")
    out += ["", "## 汇总（按类别 / 机器）", "", "| 类别 | 机器 | 项数 | 大小 |", "|---|---|---|---|"]
    grand = 0
    for (c, h), b in sorted(tot.items()):
        out.append(f"| {c} | {h} | {cnt[(c, h)]} | {human(b)} |")
        grand += b
    out.append(f"| **合计** | | {sum(cnt.values())} | **{human(grand)}** |")
    out += ["", "类别说明：assets=场景/人物图片；loras=LoRA 与旧版视频底模；voices=音色快照；renders=旧成片/BGM/审片页/渲染报告；config=配置原件（已就地删旧条目）；code=本轮未移动代码（见 docs/master/MASTER_PICTURE.md §2.3 代码残留清单）。", "",
            "## 已归档目录（项目方最终删除候选）", "", "| 路径 | 大小 | 说明 |", "|---|---|---|"]
    for p, s, n in ARCHIVED:
        out.append(f"| `{p}` | {s} | {n} |")
    out += ["", "注：任务书里写的 `data/import/backups/*60ep*` 实际不存在；60 集剧本备份按时间戳命名，上表列的 4 份经逐个读 episodes 数 = 60 确认。另 4 份 `script_v2.before_assetmaster_*` 是 10 集版，不列入。", ""]
    (Q / "MANIFEST.md").write_text("\n".join(out), encoding="utf-8")
    print(f"rows={len(rows)} moved={sum(cnt.values())} total={human(grand)}")


if __name__ == "__main__":
    main()
