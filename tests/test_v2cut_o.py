"""V2CUT-O 11-03（总调度派）：V1 数据漏进 V2（L-126 完全切割）从代码层根治，每项一组测试。

A. 导入器：非 V1 剧导入稿的 scene_library / 人物表只留本剧登记的（本集表定义过 / 本剧 P1 / 本剧资产包清单）；
   全局头带进来的别剧登记（V1 的 sk_office_night、林晚……）丢掉；V1 导入稿不能当 V2 的合并底稿。
B. 状态表 / 场景表按剧存放：V1 = data/state_timeline.json + data/scenes.json（原样），其它剧 = data/import/runs/<run>/；
   读取方一律经 ns_agent.run_paths；当前剧没有文件 → 报错 / timeline_missing，不回退 V1 全局文件。
C. ref_switch：V2 镜头只拿本剧登记的场景底图，没登记就什么都不返回。
D. V1 泄漏扫描：V2 导入稿、V2 状态表 / 场景表、V2 页面接口输出里不许出现 V1 的 id。
E. 追加（项目方 00:48 截图“确认造型：lead_f”）：资产包剧确认造型按集一条，人名 / 本集造型 / 缩略图由后端给，
   画布和通知中心同一个后端；V2 页面接口不出现裸的角色 id。
"""
from __future__ import annotations

import collections
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
V2_RUN = "series10_v2"
V2_IMPORT = REPO / "data" / "import" / "runs" / V2_RUN / "script_v2.json"
V2_DIR = V2_IMPORT.parent

# V1 的 id：显式清单 + V1 导入稿登记的人物 / 场景 id（V2 也登记了的除外）
V1_IDS_EXPLICIT = {"lin_wan", "gu_chen", "chen_yu", "ch_a_lan", "sk_office_night", "sk_gu_apartment", "sk_home_kitchen",
                   "sk_studio", "sk_elevator", "sk_alley_ballroom", "lnwan01"}


def _load_tool(name: str, rel: str):
    sp = importlib.util.spec_from_file_location(name, REPO / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def v1_ids() -> set[str]:
    ids = set(V1_IDS_EXPLICIT)
    v1 = REPO / "data" / "import" / "script_v2.json"
    v2 = json.loads(V2_IMPORT.read_text(encoding="utf-8")) if V2_IMPORT.is_file() else {}
    own = {e.get("scene_id") for e in (v2.get("globals") or {}).get("scene_library") or []} | \
          {e.get("char_id") for e in (v2.get("globals") or {}).get("character_registry") or []}
    if v1.is_file():
        g = json.loads(v1.read_text(encoding="utf-8")).get("globals") or {}
        ids |= {e.get("scene_id") for e in g.get("scene_library") or [] if e.get("scene_id")}
        ids |= {e.get("char_id") for e in g.get("character_registry") or [] if e.get("char_id")}
    return {i for i in ids if i and i not in own}


def leaks(text: str, ids: set[str]) -> dict[str, int]:
    out = {}
    for i in ids:
        n = len(re.findall(r"(?<![A-Za-z0-9_])" + re.escape(i) + r"(?![A-Za-z0-9_])", text))
        if n:
            out[i] = n
    return out


# ================================================================ A. 导入器

@pytest.fixture(scope="module")
def IS():
    return _load_tool("import_script_v2cut", "tools/import_script.py")


def _result(scenes, chars, locks=(), triggers=(), daily=""):
    from ns_schema.script import CharacterEntry, CharacterLock, LoraTrigger, SceneEntry, ScriptGlobals, ScriptImport
    g = ScriptGlobals(scene_library=[SceneEntry(scene_id=s, name=n, defined_in=d) for s, n, d in scenes],
                      character_registry=[CharacterEntry(name=n, char_id=c, defined_in=d) for n, c, d in chars],
                      character_locks=[CharacterLock(name=n, description="x") for n in locks],
                      lora_triggers=[LoraTrigger(trigger=t, kind="video", description=desc) for t, desc in triggers],
                      daily_outfit=daily)
    return ScriptImport(sources=[], globals=g, episodes=[], warnings=[])


def test_scope_globals_drops_header_only_entries(IS):
    r = _result(scenes=[("sk_office_night", "深夜写字楼办公区角落", [None]), ("sk_white_cyc", "影棚白幕", [1]),
                        ("sk_river_penthouse", "江景高层公寓", [None])],
                chars=[("林晚", "lin_wan", [None]), ("祁念", "lead_f", [1]), ("黎岸", "ch_li_an", [None])],
                locks=["林晚", "祁念"], triggers=[("lnwan01", "林晚：蓝发及腰"), ("ptxtrench", "黑色漆皮长风衣")],
                daily="林晚每天都穿得性感")
    w = IS.scope_globals(r, scenes_ok={"sk_river_penthouse"}, chars_ok={"ch_li_an", "黎岸"})
    g = r.globals
    assert [e.scene_id for e in g.scene_library] == ["sk_white_cyc", "sk_river_penthouse"]     # 本集表定义 / 本剧 P1 登记
    assert [e.char_id for e in g.character_registry] == ["lead_f", "ch_li_an"]
    assert [c.name for c in g.character_locks] == ["祁念"]
    assert [t.trigger for t in g.lora_triggers] == ["ptxtrench"] and g.daily_outfit == ""
    # 警告只记个数：导入稿里不写别剧的 id / 名字（D 的泄漏扫描也扫导入稿）
    assert w and not any(x in "".join(w) for x in ("sk_office_night", "林晚", "lin_wan", "lnwan01"))


def test_target_run_only_for_non_legacy_import_paths(IS):
    assert IS.target_run(V2_IMPORT) == V2_RUN
    assert IS.target_run(REPO / "data" / "import" / "script_v2.json") is None        # V1 导入稿：不收口（V1 原样）
    assert IS.target_run(REPO / "data" / "tmp_whatever.json") is None


def test_run_registered_reads_only_this_runs_p1_and_manifest(IS):
    scenes, chars = IS.run_registered(V2_RUN)
    assert "sk_white_cyc" in scenes and "sk_office_night" not in scenes
    assert {"lead_f", "祁念"} <= chars and not ({"lin_wan", "林晚"} & chars)


def test_v1_import_cannot_be_merge_base_for_v2(IS, monkeypatch, capsys):
    before = V2_IMPORT.read_bytes()
    monkeypatch.setattr(sys, "argv", ["import_script.py", "--script", str(REPO / "data/pipeline/runs/series10_v2/P4_ep01.final.md"),
                                      "-o", str(V2_IMPORT), "--merge-base", str(REPO / "data/import/script_v2.json"), "--no-timeline"])
    assert IS.main() == 2
    assert "V1 的导入稿" in capsys.readouterr().out
    assert V2_IMPORT.read_bytes() == before                                         # 拒绝时一个字节都没写


def test_reimported_v2_scene_library_is_only_sk_white_cyc(IS):
    """W13 CUTB-PREP 11-03：数据态陈旧（不是放宽）。原断言把 00:xx 那一刻的快照（库里只有 sk_white_cyc）写死；之后 V2 P1 / 资产包
    又登记了 5 个 V2 场景（江景高层公寓、跨年天台酒吧…），重导后库里 6 个，全是本剧的。改成本测试真正要守的性质：
    导入稿场景库里每一项都是本剧登记的（run_registered = 本剧 P1 + 资产包清单，或本集表定义过），不含任何 V1 id。"""
    g = json.loads(V2_IMPORT.read_text(encoding="utf-8"))["globals"]
    lib = {e["scene_id"]: e for e in g["scene_library"]}
    reg_scenes, _ = IS.run_registered(V2_RUN)
    assert ("sk_white_cyc", "影棚白幕") in [(e["scene_id"], e["name"]) for e in g["scene_library"]]
    stray = [sid for sid, e in lib.items() if sid not in reg_scenes and not any(d for d in e.get("defined_in") or [])]
    assert not stray, stray                                                       # 只留本剧登记 / 本集表定义的
    assert not (set(lib) & v1_ids()), set(lib) & v1_ids()                         # 不含 V1 场景
    assert all(e.get("name") for e in lib.values())


# ================================================================ B. 状态表按剧存放

@pytest.fixture()
def run_root(tmp_path):
    """临时项目根：带 tools/autopilot/runs.py + runs.json（V1 = legacy，V2 = primary）"""
    (tmp_path / "tools" / "autopilot").mkdir(parents=True)
    shutil.copy2(REPO / "tools" / "autopilot" / "runs.py", tmp_path / "tools" / "autopilot" / "runs.py")
    (tmp_path / "config" / "pipeline").mkdir(parents=True)
    (tmp_path / "config" / "pipeline" / "runs.json").write_text(json.dumps({
        "primary": "rv2", "legacy_unprefixed_run": "rv1",
        "runs": {"rv1": {"status": "archived"}, "rv2": {"status": "preparing"}}}), encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "state_timeline.json").write_text(json.dumps({"format": "ns.state_timeline/1", "shots": [
        {"shot_id": "ep01-S1", "episode": 1, "scene_id": "sk_office_night"}], "episodes": {}}), encoding="utf-8")
    (tmp_path / "data" / "scenes.json").write_text(json.dumps({"scenes": [{"scene_id": "sk_office_night"}]}), encoding="utf-8")
    return tmp_path


# 注：conftest 把真实仓库钉在 series10_v1（NS_PRIMARY_RUN）；临时根里拷的 runs.py 会把临时根当成“真实仓库”，下面各用例先去掉钉子


def test_state_paths_per_run(run_root, monkeypatch):
    from ns_agent import run_paths as RP
    from ns_agent import state_timeline as T
    monkeypatch.delenv("NS_RUN", raising=False)
    monkeypatch.delenv("NS_PRIMARY_RUN", raising=False)
    assert T.timeline_path(run_root) == run_root / "data" / "import" / "runs" / "rv2" / "state_timeline.json"
    assert T.scenes_path(run_root) == run_root / "data" / "import" / "runs" / "rv2" / "scenes.json"
    assert RP.scenes_json(run_root, "rv1") == run_root / "data" / "scenes.json"            # V1 = 全局文件
    monkeypatch.setenv("NS_RUN", "rv1")
    assert T.timeline_path(run_root) == run_root / "data" / "state_timeline.json"
    # 没有 runs.json 的临时根：旧位置（行为不变）
    bare = run_root / "bare"
    bare.mkdir()
    assert T.timeline_path(bare) == bare / "data" / "state_timeline.json"


def test_missing_current_run_timeline_raises_not_fallback(run_root, monkeypatch):
    from ns_agent import run_paths as RP
    from ns_agent import state_timeline as T
    monkeypatch.delenv("NS_RUN", raising=False)
    monkeypatch.delenv("NS_PRIMARY_RUN", raising=False)
    with pytest.raises(RP.TimelineMissing):
        RP.require_state(run_root)
    assert T.read_timeline(run_root) is None                          # 不会读到 V1 的 data/state_timeline.json


def test_sop_reads_current_run_state_only(run_root, monkeypatch):
    from ns_api import sop as SOP
    monkeypatch.delenv("NS_RUN", raising=False)
    monkeypatch.delenv("NS_PRIMARY_RUN", raising=False)
    inp = SOP.Inputs(run_root, run_root / "data" / "renders_gpu3")
    assert inp.timeline is None and inp.scenes is None                 # V1 全局文件在，但当前剧是 rv2
    assert inp.timeline_file.parent.name == "rv2"
    assert SOP.s1_gate(inp)["blockers"][0]["code"] == "timeline_missing"
    d = run_root / "data" / "import" / "runs" / "rv2"
    d.mkdir(parents=True)
    (d / "state_timeline.json").write_text(json.dumps({"format": "ns.state_timeline/1", "shots": [
        {"shot_id": "ep01-S1", "episode": 1, "scene_id": "sk_white_cyc"}], "episodes": {}}), encoding="utf-8")
    inp = SOP.Inputs(run_root, run_root / "data" / "renders_gpu3")
    assert inp.tl_shots["ep01-S1"]["scene_id"] == "sk_white_cyc"


def test_no_reader_hardcodes_global_state_files():
    """读取方不许再写死 data/state_timeline.json / data/scenes.json（唯一入口 ns_agent.run_paths.state_dir）"""
    pat = re.compile(r'"data"\s*/\s*"(state_timeline|scenes)\.json"|DATA\s*/\s*"(state_timeline|scenes)\.json"')
    allowed = {"services/agent/ns_agent/run_paths.py", "packages/qc/ns_qc/provenance.py"}   # provenance：gpu3 侧没有 ns_agent 时的旧位置
    bad = []
    for base in ("services/api/ns_api", "services/agent/ns_agent", "services/render_router/ns_render", "packages", "tools/build_state_timeline.py",
                 "tools/gen_scenes.py", "tools/import_script.py"):
        p = REPO / base
        for f in ([p] if p.is_file() else p.rglob("*.py")):
            rel = f.relative_to(REPO).as_posix()
            if rel in allowed or "/tests/" in rel:
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if pat.search(line):
                    bad.append(f"{rel}:{i}")
    assert not bad, bad


def test_v1_global_state_files_untouched_by_v2_build():
    """V2 的状态表在本剧目录；V1 全局文件仍是 V1 的（有 sk_office_night，没有 sk_white_cyc）"""
    v1 = json.loads((REPO / "data" / "state_timeline.json").read_text(encoding="utf-8"))
    assert any(s.get("scene_id") == "sk_office_night" for s in v1.get("shots") or [])
    assert (V2_DIR / "state_timeline.json").is_file() and (V2_DIR / "scenes.json").is_file()


# ================================================================ C. ref_switch

def test_ref_switch_only_registered_scenes_for_v2(monkeypatch):
    monkeypatch.setenv("NS_PRIMARY_RUN", V2_RUN)          # 真实仓库钉到 V2（conftest 默认钉 V1）
    from ns_api import ref_switch as RS
    assert not RS._legacy()
    reg = RS.run_scene_registry()
    # W13 CUTB-PREP 11-03：数据态陈旧（不是放宽）。原断言 set(reg) == {"sk_white_cyc"} 是导入稿只有 1 个场景时的快照；性质 =
    # 注册表恰好是本剧导入稿场景库（不多一个、不含 V1 id），镜头映射只落在注册表里。
    lib = {e["scene_id"] for e in json.loads(V2_IMPORT.read_text(encoding="utf-8"))["globals"]["scene_library"]}
    assert "sk_white_cyc" in reg and set(reg) <= lib and not (set(reg) & v1_ids()), set(reg)
    smap = RS.scene_map(None)
    assert set(smap.values()) <= set(reg) and "sk_office_night" not in smap.values()
    assert RS._default_plate("sk_office_night") is None                                       # V1 assets/scenes 下有图也不给
    assert RS.plate_options("sk_office_night") == [{"plate_id": "none", "scene_id": "sk_office_night", "name": "不用底图", "url": None}]


def test_ref_switch_registry_unregistered_scene_returns_nothing(monkeypatch):
    from types import SimpleNamespace as NS
    from ns_api import ref_switch as RS
    script = NS(globals=NS(scene_library=[NS(scene_id="sk_a")]),
                episodes=[NS(shots=[NS(id="ep01-S1", scene_id="sk_a"), NS(id="ep01-S2", scene_id="sk_v1_only"), NS(id="ep01-S3", scene_id=None)])])
    monkeypatch.setattr(RS, "_legacy", lambda: False)
    monkeypatch.setattr(RS, "_run_script", lambda: script)
    from ns_api import run_paths as _RP
    monkeypatch.setattr(_RP, "manifest", lambda root=None: {"scenes": {}})
    assert RS.scene_map(None) == {"ep01-S1": "sk_a"}
    assert RS._default_plate("sk_a") is None and RS._default_plate("sk_v1_only") is None


# ================================================================ D. V1 泄漏扫描

def test_leak_scan_v2_files():
    ids = v1_ids()
    for f in (V2_IMPORT, V2_DIR / "state_timeline.json", V2_DIR / "scenes.json"):
        assert not leaks(f.read_text(encoding="utf-8"), ids), (f.name, leaks(f.read_text(encoding="utf-8"), ids))


V2_GETS = ["/api/shots/ep01-S1/refs", "/api/sop/status", "/api/sop/episode/1", "/api/readiness", "/api/v2/assets", "/api/episodes", "/api/episodes/1",
           "/api/episodes/summary", "/api/assets/scenes", "/api/owner/inbox"]


_API_PROBE = r"""
import json, os, sys
from fastapi.testclient import TestClient
from ns_api import look_confirm as LC
LC.sync_picks = lambda root=None: []          # 只读扫描：不往真实通知队列投递
from ns_api.app import app
c = TestClient(app)
out = {}
for u in json.loads(sys.argv[1]):
    r = c.get(u)
    out[u] = {"status": r.status_code, "json": r.json() if r.headers.get("content-type", "").startswith("application/json") else None}
sys.stdout.write(json.dumps(out, ensure_ascii=False))
"""


@pytest.fixture(scope="module")
def api():
    """V2 页面接口输出：子进程里把真实仓库钉到 V2 再起 app（ns_render.pipeline 在导入时就按当前剧取剧本，不能在本进程里换剧）"""
    import os
    import subprocess
    env = {**os.environ, "NS_PRIMARY_RUN": V2_RUN, "PYTHONIOENCODING": "utf-8", "NS_TIMELINE_AUTOBUILD": "0"}
    env.pop("NS_RUN", None)
    r = subprocess.run([sys.executable, "-c", _API_PROBE, json.dumps(V2_GETS)], cwd=REPO, env=env, capture_output=True, timeout=900)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-2000:]
    return json.loads(r.stdout.decode("utf-8"))


def test_leak_scan_v2_api_outputs(api):
    ids = v1_ids()
    found = {}
    for u in V2_GETS:
        r = api[u]
        if r["status"] == 404:
            continue
        assert r["status"] == 200, (u, r["status"])
        if u == "/api/owner/inbox":        # 通知中心混着别的线（V1 视频库归档提醒等）的条目：只扫 V2 的条目
            text = json.dumps([i for i in r["json"].get("items") or [] if V2_RUN in json.dumps(i, ensure_ascii=False)], ensure_ascii=False)
        else:
            text = json.dumps(r["json"], ensure_ascii=False)
        if (lk := leaks(text, ids)):
            found[u] = lk
    assert not found, found


# ================================================================ E. 确认造型：人名 / 本集造型 / 缩略图；不出现裸 cid

CID_RE = re.compile(r"(?<![A-Za-z0-9_/.=-])(lead_[a-z]+|ch_[a-z][a-z0-9_]*)(?![A-Za-z0-9_])")
ID_KEYS = {"cid", "character", "id", "char_id", "character_id", "pick_id", "speaker_id", "slug", "primary"}   # 机器字段（primary = asset_refs 记录的主角色 id），前端不直接显示


def bare_cids(obj) -> dict[str, str]:
    out: dict[str, str] = {}

    def walk(o, key, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, k, f"{path}.{k}")
        elif isinstance(o, list):
            for v in o:
                walk(v, key, f"{path}[]")
        elif isinstance(o, str) and key not in ID_KEYS and not o.startswith(("/", "assets", "data/", "http")) and CID_RE.search(o):
            out[path] = o[:120]
    walk(obj, None, "")
    return out


def test_v2_page_apis_have_no_bare_cid(api):
    for u in ("/api/sop/status", "/api/sop/episode/1", "/api/shots/ep01-S1/refs", "/api/episodes/1", "/api/readiness"):
        assert api[u]["status"] == 200
        assert not bare_cids(api[u]["json"]), (u, bare_cids(api[u]["json"]))


def test_v2_look_action_per_episode_with_names_and_thumbs(api, monkeypatch):
    """W13 CUTB-PREP 11-03：数据态陈旧（不是放宽）。原断言写于 ep01 造型未确认时（“应有一条确认造型”）；项目方 02:23 已确认 ep01，
    真实数据翻转后必红（第 18 / 25 / 28 轮已定性）。改成两态性质：读同一后端 look_confirm.episode_state —— 已确认 → 画布不再挂
    确认造型动作；未确认 → 有一条，人名 / 本集造型 / 缩略图由后端给（look_id 跟排期走，不写死）。"""
    monkeypatch.setenv("NS_PRIMARY_RUN", V2_RUN)
    from ns_api import look_confirm as LC
    st = LC.episode_state(REPO, V2_RUN, 1)
    acts = [a for a in api["/api/sop/episode/1"]["json"].get("owner_actions") or [] if a.get("gate") == "look"]
    if st["confirmed"]:
        assert not acts, acts
        return
    assert acts, "第 1 集造型没确认，应有一条确认造型"
    a = acts[0]
    assert a["per_episode"] and a["episodes"] == [1] and a["title"].startswith("确认第 1 集造型：")
    by = {p["cid"]: p for p in a["people"]}
    want = {p["cid"]: p for p in st["people"]}
    assert by["lead_f"]["display_name"] == "祁念" and by["lead_f"]["look_id"] == want["lead_f"]["look_id"]
    assert by["lead_f"]["thumb_url"] and by["lead_f"]["thumb_url"].startswith("/api/v2/asset-file?")
    assert "lead_f" not in a["title"] and "lead_f" not in a["character_name"]
    assert a["actionable"] == all(p["ready"] for p in a["people"])


@pytest.fixture()
def lc_env(tmp_path, monkeypatch):
    """临时根 + 假的本集人物：只测 look_confirm 的确认 / 通知投递 / 关闭逻辑，不碰真实队列和清单"""
    from ns_api import look_confirm as LC
    people = [{"cid": "lead_f", "display_name": "祁念", "look_id": "O4", "look_name": "日常", "thumb_url": "/api/v2/asset-file?path=x",
               "thumb_note": None, "ready": True, "wait": None}]
    state = {"people": people}
    monkeypatch.setattr(LC, "current_run", lambda root=None: "rv2")
    monkeypatch.setattr(LC, "episode_people", lambda root, run, ep: [dict(p) for p in state["people"]])
    from types import SimpleNamespace as NS
    monkeypatch.setattr(LC, "_script", lambda root, run: NS(episodes=[NS(number=1)]))
    return tmp_path, LC, state


def test_look_confirm_canvas_and_inbox_same_backend(lc_env):
    from ns_api import owner_pick as OP
    from ns_api import owner_queue as OQ
    root, LC, state = lc_env
    ids = LC.sync_picks(root)
    assert len(ids) == 1 and ids[0].startswith("pick:look:rv2:ep01:")
    req = next(r for r in OQ.requests(root) if r["id"] == ids[0])
    assert req["people"][0]["display_name"] == "祁念" and [c["key"] for c in req["candidates"]] == ["confirm"]
    assert OP.wired(ids[0])
    assert LC.sync_picks(root) == ids and len([r for r in OQ.requests(root) if r["id"].startswith("pick:look:")]) == 1   # 不重投
    # 画布确认 → 记录写下、通知关掉
    rec = LC.confirm(root, "rv2", 1, "owner", "可以", via="canvas")
    assert rec["looks"] == {"lead_f": "O4"} and LC.episode_state(root, "rv2", 1)["confirmed"]
    assert ids[0] in OQ._closed(root, __import__("time").time())
    assert LC.sync_picks(root) == []
    # 排期改了 → 快照对不上 → 重新要确认（新 id）
    state["people"][0]["look_id"] = "O1"
    assert not LC.episode_state(root, "rv2", 1)["confirmed"]
    new = LC.sync_picks(root)
    assert new and new != ids
    # 通知里确认（owner_pick 处理器）→ 同一份记录
    res = LC.apply_pick(root, {"id": new[0], "run": "rv2", "episode": 1}, "confirm", "owner")
    assert res["looks"] == {"lead_f": "O1"} and LC.episode_state(root, "rv2", 1)["confirmed"]


def test_look_confirm_refuses_when_assets_not_ready(lc_env):
    root, LC, state = lc_env
    state["people"].append({"cid": "ch_zhuo_lin", "display_name": "卓琳", "look_id": None, "look_name": "本集还没排造型",
                            "thumb_url": None, "ready": False, "wait": "卓琳的形象还在出候选，选定后再确认造型"})
    assert LC.sync_picks(root) == []                         # 没就绪不投通知（不重复要求项目方做事）
    with pytest.raises(ValueError, match="卓琳的形象还在出候选"):
        LC.confirm(root, "rv2", 1, "owner")


# ================================================================ C'. 资产包底图（assets_v2）不再写死 assets/scenes（总调度 01:0x）

def test_ref_switch_assets_plate_id_by_asset_root():
    from ns_api import ref_switch_assets as RA
    assert RA._plate_id("assets/scenes/sk_a/plate.png") == "sk_a/plate.png"                       # V1：相对 assets/scenes（旧口径不变）
    v2 = "assets_v2/scenes/sk_white_cyc/sk_white_cyc_base_sk_white_cyc#2.png"
    assert RA._plate_id(v2) == v2                                                                # 资产包：原路径，不再 relative_to 崩
    u = RA._plate_url(v2)
    if (REPO / v2).is_file():
        assert u.startswith("/api/v2/asset-file?path=assets_v2/scenes/") and "%232.png" in u      # # 要编码，否则被当锚点截断


def test_v2_refs_returns_registered_v2_plate(api):
    sc = api["/api/shots/ep01-S1/refs"]["json"]["scene"]
    man = json.loads((REPO / "assets_v2" / "manifest.json").read_text(encoding="utf-8"))
    base = (((man.get("scenes") or {}).get("sk_white_cyc") or {}).get("base") or {}).get("file")
    if not base:
        assert sc["effective"]["plate_id"] in (None, "none")                                     # 没登记 = 什么都不给
    else:
        assert sc["effective"]["plate_id"] == base and sc["effective"]["url"].startswith("/api/v2/asset-file?")
        assert all(o["plate_id"] in (base, "none") for o in sc["options"])                       # 候选只列本剧登记的那张
