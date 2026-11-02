"""两台重复出图逐镜合并（K-OPS-W27）：判定 ①–④、同号不同图换号、笔记本隔离标记带进来；merge_takes 按文件认版本。纯数据，不碰服务器。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops/offline"))
import merge_pull as MP  # noqa: E402
import resolve_dup_takes as RD  # noqa: E402


def T(stage, n, f, ok, **kw):
    return {"stage": stage, "n": n, "file": f"renders/ep08/S3/takes/{f}", "postflight": {"ok": ok}, **kw}


def test_decide_rules():
    d36 = {"active": {"image": 8}, "takes": [T("image", 8, "i8_36.png", True)]}
    d33 = {"active": {"image": 5}, "takes": [T("image", 5, "i5_33.png", True)]}
    assert RD.decide("image", d36, d33, [5])["rule"] == "③" and RD.decide("image", d36, d33, [5])["use"] == "gpu36"
    d33f = {"active": {"image": 5}, "takes": [T("image", 5, "i5_33.png", False)]}
    assert RD.decide("image", d36, d33f, [5])["use"] == "gpu36"                         # ② 只有 gpu36 过
    d36f = {"active": {"image": 8}, "takes": [T("image", 8, "i8_36.png", False)]}
    r = RD.decide("image", d36f, d33, [5])
    assert r["rule"] == "②" and r["use"] == "gpu33" and r["quarantine_33"] == []
    r = RD.decide("image", d36f, d33f, [5])
    assert r["rule"] == "④" and r["use"] == "both" and r["quarantine_33"] == []
    lk = {**d36f, "locked": {"image": 8}}
    r = RD.decide("image", lk, d33, [5])
    assert r["rule"] == "①" and r["use"] == "gpu36"                                    # ① 锁定优先于契约


def test_merge_renumbers_collisions_and_quarantines_loser():
    d33 = {"active": {"image": 5}, "takes": [T("image", 4, "same.png", True), T("image", 5, "i5_33.png", True)]}
    d36 = {"active": {"image": 5}, "takes": [T("image", 4, "same.png", True), T("image", 5, "i5_36.png", True)]}
    decs = [RD.decide("image", d36, d33, [5])]
    doc, _ = RD.merged_doc(d33, d36, decs, "t", "now")
    files = {(t["n"], t["file"].rsplit("/", 1)[1]): t for t in doc["takes"]}
    assert (4, "same.png") in files and (5, "i5_33.png") in files and (6, "i5_36.png") in files   # 同文件认同一版本；同号不同图换新号
    assert files[(6, "i5_36.png")]["renumbered"]["from_n"] == 5
    assert doc["active"]["image"] == 6 and files[(5, "i5_33.png")]["quarantined"]                 # ③ 用 gpu36（换号后），gpu33 那份隔离
    assert len(doc["takes"]) == 3                                                                    # 不丢任何版本


def test_fold_local_quarantine():
    doc = {"active": {"last": 1}, "takes": [T("last", 1, "l1.png", True)]}
    lap = {"takes": [T("last", 7, "l1.png", True, quarantined={"by": "UIRSI r41"})]}
    out = RD.fold_local_quarantine(doc, lap)
    assert out["takes"][0]["quarantined"]["by"] == "UIRSI r41" and "last" not in out["active"]


def test_merge_takes_docs_idempotent_by_file():
    l = {"active": {"image": 5}, "takes": [T("image", 5, "a.png", True)]}
    r = {"active": {"image": 5}, "takes": [T("image", 5, "b.png", True)]}
    out, added, _u, remap = MP.merge_takes_docs(r, l)
    assert added == 1 and remap[("image", 5)] == 6 and out["active"]["image"] == 6
    out2, added2, _u2, _r2 = MP.merge_takes_docs(r, out)                 # 再并一次：按文件认出已有的 #6，不重复追加
    assert added2 == 0 and len(out2["takes"]) == 2
