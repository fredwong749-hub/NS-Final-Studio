"""ASSETUX R2（L-120）：统一动作 select / reject / trash + prompt_rewrite 新 kind + 通用生成状态（GenState）。
复用 test_character_hub_assetux 的临时项目夹具，不碰生产数据。"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ns_agent import asset_refs as R
from ns_api import asset_actions as AA
from ns_api import character_hub as H
from ns_api import prompt_rewrite as PR

from test_character_hub_assetux import PJ, env  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]
SH = "data/pipeline/runs/testproj/images/sheets/lin_wan/lin_wan_look{l}_s{s}.png"


@pytest.fixture()
def c(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(H, "face_crop_check", lambda p: (True, "夹具"))
    env["c"].app.include_router(AA.router)
    return env["c"]


def test_select_sheet_requires_impact_ack_and_returns_undo(c):
    f101 = SH.format(l="A", s=101)
    r = c.post("/api/assets/lin_wan/select", json={"kind": "sheet", "cid": "lin_wan", "look": "A", "file": f101})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "impact_ack_required"      # 没给项目方看影响数不许换
    assert R.sheet_of(PJ, "lin_wan", "A").endswith("s202.png")                                # 没生效
    r = c.post("/api/assets/lin_wan/select", json={"kind": "sheet", "cid": "lin_wan", "look": "A", "file": f101, "impact_ack": 12})
    assert r.status_code == 200
    j = r.json()
    assert R.sheet_of(PJ, "lin_wan", "A") == f101 and j["prev"].endswith("s202.png")
    assert j["undo"] == {"how": "select", "file": j["prev"]}
    r2 = c.post("/api/assets/lin_wan/select", json={"kind": "sheet", "cid": "lin_wan", "look": "A", "file": j["prev"], "impact_ack": 12})
    assert r2.status_code == 200 and R.sheet_of(PJ, "lin_wan", "A") == j["prev"]


def test_select_face_ack_must_match_server_count(c, monkeypatch):
    other = "data/pipeline/runs/testproj/images/sheets/lin_wan/lin_wan_face_ref.png"
    monkeypatch.setattr(AA, "impact_counter", lambda cid, kind, look: 37)
    body = {"kind": "face", "cid": "lin_wan", "file": other}
    assert c.post("/api/assets/lin_wan/select", json=body).status_code == 409
    r = c.post("/api/assets/lin_wan/select", json={**body, "impact_ack": 5})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "impact_changed" and r.json()["detail"]["impact"] == 37
    assert R.face_of(PJ, "lin_wan") == "assets/characters/lin_wan/refs/face1.png"
    assert c.post("/api/assets/lin_wan/select", json={**body, "impact_ack": 37}).status_code == 200
    assert R.face_of(PJ, "lin_wan") == other


def test_select_scene_plate_is_honest_501_and_bad_kind_422(c):
    assert c.post("/api/assets/x/select", json={"kind": "scene_plate", "cid": "lin_wan", "file": "a.png"}).status_code == 501
    assert c.post("/api/assets/x/select", json={"kind": "voice", "cid": "lin_wan", "file": "a.png"}).status_code == 422


def test_reject_needs_reason_refuses_current_and_can_restore(c, env):
    cur = SH.format(l="A", s=202)
    other = SH.format(l="A", s=101)
    base = {"kind": "sheet", "cid": "lin_wan", "look": "A"}
    assert c.post("/api/assets/lin_wan/reject", json={**base, "file": other}).status_code == 422                       # 必记原因
    assert c.post("/api/assets/lin_wan/reject", json={**base, "file": cur, "reasons": ["画质差"]}).status_code == 409   # 当前图不能直接收起
    assert c.post("/api/assets/lin_wan/reject", json={**base, "file": other, "reasons": ["不像本人"], "note": "脸偏"}).status_code == 200
    assert H.rejected_map()[other]["reasons"] == ["不像本人"]
    assert (env["root"] / other).is_file()                                                                              # 文件还在
    assert c.post("/api/assets/lin_wan/reject", json={**base, "file": other, "undo": True}).status_code == 200           # 恢复
    assert other not in H.rejected_map()


def test_trash_quarantines_not_deletes_and_refuses_current(c, env):
    cur = SH.format(l="A", s=202)
    other = SH.format(l="A", s=101)
    base = {"kind": "sheet", "cid": "lin_wan", "look": "A"}
    assert c.post("/api/assets/lin_wan/trash", json={**base, "file": cur}).status_code == 409
    r = c.post("/api/assets/lin_wan/trash", json={**base, "file": other})
    assert r.status_code == 200, r.text
    eid = r.json()["entry_id"]
    assert not (env["root"] / other).exists()                       # 离开原位
    assert list((env["root"] / "data" / "_trash").rglob("*s101.png")), "文件应当在回收区（隔离，不是 unlink）"
    assert c.post(f"/api/trash/{eid}/restore").status_code == 200
    assert (env["root"] / other).is_file()                          # 可恢复
    assert c.post("/api/assets/lin_wan/trash", json={**base}).status_code == 422   # 说不清移哪个


def test_prompt_rewrite_new_kinds_use_right_system_file_and_context(monkeypatch):
    assert PR.system_path("sheet") == PR.SYSTEM_FILE and PR.system_path("scene_plate") == PR.SYSTEM_FILE
    for k in ("edit_mask", "new_look", "new_item"):
        assert PR.system_path(k) == PR.EDIT_FILE and PR.EDIT_FILE.is_file()
    with pytest.raises(PR.RewriteError):
        PR.system_path("voice")
    assert "场景" in PR.SYSTEM_FILE.read_text(encoding="utf-8") and "框选" in PR.EDIT_FILE.read_text(encoding="utf-8")
    u = PR.build_user("edit_mask", "手指不对", {"name": "林晚", "region": "左上 30%x20%"})
    assert "框选的区域" in u and "左上 30%x20%" in u
    seen = {}

    def chat(msgs):
        seen["sys"] = msgs[0]["content"]
        return {"content": json.dumps({"prompt": "Keep everything outside the edited region exactly unchanged; fix fingers", "negative_add": "", "zh_summary": "只修手指"}), "model": "t", "usd": 0}
    monkeypatch.setattr(PR, "_spent_today", lambda: 0.0)
    r = PR.rewrite("edit_mask", "手指不对", {"region": "x"}, chat=chat)
    assert r["zh_summary"] == "只修手指" and "局部修改" in seen["sys"]


def test_rewrite_preview_endpoint_502_on_gateway_failure(c, monkeypatch):
    def boom(kind, text, ctx, chat=None):
        raise PR.RewriteError("网关挂了")
    monkeypatch.setattr(PR, "rewrite", boom)
    r = c.post("/api/assets/rewrite", json={"kind": "edit_mask", "text": "修手"})
    assert r.status_code == 502 and "没有出图" in r.json()["detail"]                 # 不退回本地硬写
    assert c.post("/api/assets/rewrite", json={"kind": "edit_mask", "text": " "}).status_code == 422
    monkeypatch.setattr(PR, "rewrite", lambda k, t, x, chat=None: {"prompt": "p" * 30, "negative_add": "", "zh_summary": "一句", "model": "m"})
    assert c.post("/api/assets/rewrite", json={"kind": "new_look", "text": "风衣"}).json()["zh_summary"] == "一句"


JS = """
import { genView, fmtRemain } from "./apps/web/src/v3/GenState.helpers.ts";
const now = Date.parse("2026-11-02T16:00:00");
const all = [
 {id:"a", state:"running", gpu:1, kind:"frame", created_at:"2026-11-02T15:58:00", started_at:"2026-11-02T15:59:00", eta_s:100},
 {id:"b", state:"queued", gpu:1, kind:"frame", created_at:"2026-11-02T15:59:10", eta_s:200},
 {id:"c", state:"queued", gpu:1, kind:"frame", created_at:"2026-11-02T15:59:20"},
 {id:"d", state:"queued", gpu:2, kind:"frame", created_at:"2026-11-02T15:59:05"},
 {id:"h", state:"done", gpu:1, kind:"frame", wall_s:60},
 {id:"e", state:"failed", error:"oom"}, {id:"f", state:"done"}];
const o = {};
o.run = genView(all[0], all, now); o.q2 = genView(all[1], all, now); o.q3 = genView(all[2], all, now); o.other = genView(all[3], all, now);
o.fail = genView(all[5], all, now); o.done = genView(all[6], all, now); o.none = genView(undefined, all, now);
o.t = [fmtRemain(3), fmtRemain(40), fmtRemain(150), fmtRemain(null), fmtRemain(90, true)];
console.log(JSON.stringify(o));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="no node")
def test_genstate_helpers_queue_eta_and_done():
    out = subprocess.run(["node", "--input-type=module", "-e", JS], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr[-600:]
    o = json.loads(out.stdout)
    assert o["run"]["phase"] == "running" and o["run"]["queuePos"] == 0 and o["run"]["remainS"] == 40 and not o["run"]["estimated"]
    assert o["q2"]["phase"] == "queued" and o["q2"]["queuePos"] == 1        # 前面只有正在跑的 a：它跑完就轮到 b
    assert o["q3"]["queuePos"] == 2 and o["q3"]["estimated"] is True        # 没有 eta_s：历史中位 60 s x 3
    assert o["other"]["queuePos"] == 1                                       # 别的卡不算
    assert o["fail"]["phase"] == "failed" and o["fail"]["error"] == "oom" and o["done"]["phase"] == "done" and o["none"] is None
    assert o["t"] == ["快好了", "约 40 秒", "约 3 分钟", "时间还不确定", "估计 2 分钟"]


def test_frontend_wiring_genstate_on_asset_regen():
    web = ROOT / "apps" / "web" / "src" / "v3"
    hub = (web / "assets" / "PeopleHub.tsx").read_text(encoding="utf-8")
    assert "trackGen(" in hub and "<GenPoller" in hub and "<GenDock" in hub
    assert "else window.setTimeout(reload, 60000)" in hub                                   # 只有没拿到 job 才退回老的盲等
    assert hub.count("<GenTiles") >= 5                                                      # 设定图 x2、身份脸、单品 x2
    g = (web / "GenState.tsx").read_text(encoding="utf-8")
    assert "export function GenTiles" in g and "export function GenDock" in g and "export const useJobs" in g
    css = (web / "genstate.css").read_text(encoding="utf-8")
    assert "ns-breathe" in css and "red" not in css.lower()


def test_shots_using_counts_like_render_and_wires_into_select(c, monkeypatch, env):
    """影响数服务端算法：在画 / 局部才算（画外不算）；造型按 排期 > 逐镜登记 解析；face = 全部出场镜，sheet = 该造型的镜"""
    from ns_api import shot_cast as SC
    (env["looks_dir"] / "hub_episode_looks.json").write_text(json.dumps({PJ: {"lin_wan": {"2": "B"}}}), encoding="utf-8")
    monkeypatch.setattr(R, "registry_looks", lambda project: {"ep01-S2": {"lin_wan": "A"}})
    doc = {"episodes": [
        {"number": 1, "shots": [
            {"index": 1, "cast": [{"name": "林晚", "presence": "在画"}]},
            {"index": 2, "cast": [{"name": "林晚", "presence": "局部"}, {"name": "顾沉", "presence": "在画"}]},
            {"index": 3, "cast": [{"name": "林晚", "presence": "画外"}]},
            {"index": 4, "cast": [{"name": "顾沉", "presence": "在画"}]}]},
        {"number": 2, "shots": [{"index": 1, "cast": [{"name": "林晚", "presence": "在画"}]}]}]}
    assert SC.shots_using(doc, PJ, "lin_wan") == ["ep01-S1", "ep01-S2", "ep02-S1"]
    assert SC.shots_using(doc, PJ, "lin_wan", "A") == ["ep01-S2"]
    assert SC.shots_using(doc, PJ, "lin_wan", "B") == ["ep02-S1"]
    assert SC.shots_using(doc, None, "lin_wan") == []
    # 接进 select：确认数对不上 → 409，带服务端数
    monkeypatch.setattr(AA, "impact_counter", lambda cid, kind, look: len(SC.shots_using(doc, PJ, cid, look if kind == "sheet" else None)))
    f101 = SH.format(l="A", s=101)
    body = {"kind": "sheet", "cid": "lin_wan", "look": "A", "file": f101}
    r = c.post("/api/assets/lin_wan/select", json={**body, "impact_ack": 9})
    assert r.status_code == 409 and r.json()["detail"]["impact"] == 1
    assert c.post("/api/assets/lin_wan/select", json={**body, "impact_ack": 1}).status_code == 200
