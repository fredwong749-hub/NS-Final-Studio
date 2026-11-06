"""阶段 A 资产作业（M-AUTOPIPE-01，AUTOPIPE-A 11-03）：全部用临时目录 + 夹具，不碰真实清单 / 队列 / GPU。
模拟“第 1 集缺 3 个人的脸、1 个场景、1 个音色”一整轮：生成作业 → 执行器（假出图 / 假音色链）→ 待办通知 → 项目方选定（owner_pick 统一入口）
→ 登记清单 → 重跑就绪检查 → 写“可以出金样首帧”作业。"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/post", "services/agent", "services/api", "tools/pipeline"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import asset_checks as AC  # noqa: E402
import asset_jobs as AJ  # noqa: E402
import asset_worker as AW  # noqa: E402
from ns_agent.gen_contract import preflight as PF  # noqa: E402
from ns_api import owner_pick as OP  # noqa: E402
from ns_post import run_media as RM  # noqa: E402

RUN = "demo_v2"
CIDS = {"ch_zhuo_lin": "卓琳", "ch_tang_yao": "唐瑶", "ch_jiang_yubai": "江予白"}


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _w(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(d if isinstance(d, bytes) else json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8"))


def _j(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------ 夹具：一部剧、第 1 集、P1、清单、开关
@pytest.fixture()
def root(tmp_path, monkeypatch):
    r = tmp_path
    _w(r / "config/pipeline/runs.json", {"primary": RUN, "legacy_unprefixed_run": "series10_v1",
                                         "runs": {RUN: {"status": "preparing", "episode": 1, "assets_manifest": "assets_v2/manifest.json"},
                                                  "old": {"status": "archived", "episode": 3}}})
    _w(r / "config/pipeline/asset_worker.json", {"enabled": True, "apply_meta": True, "render": True, "voice": True, "push": False,
                                                 "max_parallel": 2, "exclude_lanes": ["gpu33:2", "gpu36:2"], "max_attempts": 2, "ready_every_s": 0,
                                                 "candidates": {"face": 2, "scene": 2, "sheet": 2, "item": 2}})
    _w(r / f"data/import/runs/{RUN}/script_v2.json", {"episodes": [{"number": 1, "shots": [{"index": i} for i in range(1, 4)]}]})
    chars = [{"name": n, "char_id": c, "role": "配角", "age": 30, "gender": "女" if c != "ch_jiang_yubai" else "男",
              "zh_look": "三十岁｜匀称｜黑色齐肩直发｜酒红与黑｜鲜红色长指甲｜薄唇", "en_phrase": "x", "voice_phrase": "a crisp bright alto voice"} for c, n in CIDS.items()]
    _w(r / f"data/pipeline/runs/{RUN}/P1_storyline.json", {"characters": chars, "scenes": [
        {"scene_id": "sk_white_cyc", "name": "影棚白幕", "space": "纯白无缝弧形背景幕", "time_of_day": "日", "light": "环形灯正面高亮"}]})
    _w(r / f"data/pipeline/runs/{RUN}/P1_looks.json", [{"char_id": c, "name": n, "looks": [
        {"id": "A", "use": "试镜：ep01", "zh": "服装=酒红色西装套装｜鞋=黑色细高跟｜饰品=无", "en": "a wine-red suit"}]} for c, n in CIDS.items()])
    _w(r / "assets_v2/manifest.json", {"schema": "nsfs.assets_manifest/1", "run": RUN, "locked": False, "characters": {"lead_f": {"display_name": "祁念"}}, "scenes": {}})
    _w(r / "data/owner_queue/requests.json", [])
    lead_ref = b"lead-ref"
    _w(r / "data/assets/voices_v2/lead_f/b/ref.wav", lead_ref)
    _w(r / "data/assets/voices_v2/lead_f/b/meta.json", {"gender": "female"})
    _w(r / "config/voices_v2.json", {"enabled": True, "status": "owner_picked",
                                     "roles": {"lead_f": {"persona": "p", "selected": "b", "candidates": [
                                         {"cand": "b", "dir": "data/assets/voices_v2/lead_f/b", "ref_wav": "data/assets/voices_v2/lead_f/b/ref.wav",
                                          "enabled": True, "selected": True, "ref_sha256": _sha(lead_ref)}]}},
                                     "cast_voice": {"map": {"lead_f": "lead_f"}, "why": {}}, "support_candidates": {"roles": {}}})
    _w(r / "config/voices.json", {})
    _w(r / "docs/master/V2_LIVE.md", "# V2 LIVE\n")
    monkeypatch.setattr(OP, "REPO", r)
    monkeypatch.setattr(OP, "_AJ", AJ)
    monkeypatch.setattr(RM, "is_asset_pack_run", lambda run, root=ROOT: True)
    monkeypatch.setattr(RM, "_speaker_cast", lambda run, root: {"names": {"祁念": "lead_f", "卓琳": "ch_zhuo_lin"}, "male": [], "female": ["lead_f", "ch_zhuo_lin"], "lead": "lead_f", "source": "fixture"})
    return r


def fake_check(root: Path):
    """episode_ready 的替身：按夹具里的清单 / 音色配置现算缺口（口径与 tools/master/episode_ready.py 一致：face / name / scene / voice）"""
    def check(run: str, episode: int) -> dict:
        man = _j(root / "assets_v2/manifest.json")
        voices = _j(root / "config/voices_v2.json")
        gaps = []
        for cid, name in CIDS.items():
            e = (man.get("characters") or {}).get(cid) or {}
            if not (e.get("face") or {}).get("file"):
                gaps.append({"kind": "face", "who": f"{name}（{cid}）", "what": "没有身份脸", "owner": "资产线", "shots": [1]})
            if not e.get("display_name"):
                gaps.append({"kind": "name", "who": f"{name}（{cid}）", "what": "清单里没有 display_name", "owner": "资产线", "shots": [1]})
        if not ((man.get("scenes") or {}).get("sk_white_cyc") or {}).get("base"):
            gaps.append({"kind": "scene", "who": "sk_white_cyc", "what": "场景 sk_white_cyc 没有参考底图", "owner": "资产线", "shots": [1, 2]})
        if "zhuo_lin" not in (voices.get("roles") or {}):
            gaps.append({"kind": "voice", "who": "卓琳（ch_zhuo_lin）", "what": "还没有选定音色", "owner": "项目方", "shots": [2]})
        return {"run": run, "episode": episode, "ready": not gaps, "gaps": gaps,
                "shots": [{"index": 1, "adult": False}, {"index": 2, "adult": False}, {"index": 3, "adult": True}]}
    return check


def fake_renderer(root: Path):
    def render(job, lane, seed, _root):
        rd = AW.review_dir(root, job)
        rd.mkdir(parents=True, exist_ok=True)
        f = rd / f"{job['id']}_s{seed}.png"
        f.write_bytes(f"png-{job['id']}-{seed}-{lane}".encode())
        rel = str(f.relative_to(root)).replace("\\", "/")
        return {"seed": seed, "passed": True, "label": {"count": "pass", "q9": "pass", "prompt_vlm": "pass", "ocr": "pass", "age": "pass"},
                "review_file": rel, "thumb": rel, "sha256": _sha(f.read_bytes()), "file": rel}
    return render


def fake_voice_runner(root: Path, role: str):
    def run(args):
        if args[0] == "page":        # 假 voice_v2 page --roles：写 support_candidates + 候选文件（格式与 VOICE-S 的一致）
            cands = []
            for k in "abc":
                d = f"data/assets/voices_v2/{role}/{k}"
                ref = f"ref-{k}".encode()
                _w(root / d / "ref.wav", ref)
                _w(root / d / "sample.wav", f"sample-{k}".encode())
                _w(root / d / "meta.json", {"gender": "female"})
                _w(root / f"data/review_pages/v2_style/voice/{role}_{k}_sample.wav", f"sample-{k}".encode())
                cands.append({"cand": k, "dir": d, "accent": "x", "shanghai_accent": k != "a", "ref_sha256": _sha(ref), "f0_hz": 250.0, "enabled": False, "status": "待选"})
            cfg = _j(root / "config/voices_v2.json")
            cfg["support_candidates"]["roles"][role] = {"persona": "p", "char_id": "ch_zhuo_lin", "candidates": cands, "selected": None}
            _w(root / "config/voices_v2.json", cfg)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return run


class FakeLanes:
    def __init__(self):
        self.held, self.released = [], []

    def hold(self, lane, minutes, why, by=None, **k):
        self.held.append((lane, by))

    def release(self, lane, by=None, kind=None, **k):
        self.released.append((lane, by, kind))


def make_spawn(root: Path, cfg: dict):
    """起子进程的替身：同步跑 run_job / run_voice（假出图 / 假音色链），返回已结束的“进程”"""
    def spawn(job, jp, lane):
        if job["kind"] == "voice":
            AW.run_voice(jp, root, runner=fake_voice_runner(root, job["spec"]["role"]), remote_ready=lambda *a: True, cfg=cfg)
        else:
            AW.run_job(jp, lane, root, renderer=fake_renderer(root), cfg=cfg)
        return SimpleNamespace(pid=0, poll=lambda: 0)
    return spawn


# ------------------------------------------------------------------ 1）作业生成：幂等、按类型、接管已有 pick
def test_generate_jobs_from_gaps_is_idempotent(root):
    g = AJ.generate(RUN, 1, root, check=fake_check(root))
    assert sorted(g["created"]) == sorted(["face-ch_zhuo_lin", "face-ch_tang_yao", "face-ch_jiang_yubai", "meta-name-ch_zhuo_lin", "meta-name-ch_tang_yao",
                                           "meta-name-ch_jiang_yubai", "scene-sk_white_cyc", "voice-ch_zhuo_lin"])
    jobs = {j["id"]: j for j in AJ.list_jobs(root, RUN)}
    assert jobs["face-ch_zhuo_lin"]["pick_id"] == "pick:face:ch_zhuo_lin" and jobs["voice-ch_zhuo_lin"]["pick_id"] == "pick:voice_v2:zhuo_lin"
    assert "卓琳" in jobs["face-ch_zhuo_lin"]["spec"]["img"] and "30岁" in jobs["face-ch_zhuo_lin"]["spec"]["desc"]
    assert jobs["scene-sk_white_cyc"]["spec"]["img"].startswith("空镜，无人物")
    assert jobs["meta-name-ch_tang_yao"]["spec"] == {"op": "name", "cid": "ch_tang_yao", "display_name": "唐瑶"}
    g2 = AJ.generate(RUN, 1, root, check=fake_check(root))
    assert g2["created"] == [] and len(g2["existing"]) == 8 and (AJ.jobs_dir(root, RUN) / "_ready_ep01.json").is_file()


def test_generate_adopts_existing_pick_from_cast_s(root):
    """CAST-S 已投的 v2cast-<对象> 条目：作业直接接管（awaiting_pick），不再出候选"""
    f = root / "data/review_pages/v2_cast/ch_tang_yao_s1002.png"
    _w(f, b"cast-s-png")
    _w(root / "data/owner_queue/requests.json", [{"id": "v2cast-ch_tang_yao", "kind": "pick", "title": "挑一张：唐瑶", "by": "CAST-S",
                                                  "candidates": [{"key": "ch_tang_yao#1", "label": "唐瑶 候选1", "file": "data/review_pages/v2_cast/ch_tang_yao_s1002.png", "contract_ok": True}]}])
    g = AJ.generate(RUN, 1, root, check=fake_check(root))
    assert "face-ch_tang_yao ← v2cast-ch_tang_yao" in g["adopted"]
    j = AJ.load_job(AJ.job_path(root, RUN, "face-ch_tang_yao"))
    assert j["state"] == "awaiting_pick" and j["pick_id"] == "v2cast-ch_tang_yao" and j["candidates"][0]["key"] == "ch_tang_yao#1"
    assert AJ.pick_object("v2cast-ch_tang_yao") == ("face", ["ch_tang_yao"]) and AJ.pick_object("v2cast-sk_white_cyc") == ("scene", ["sk_white_cyc"])
    assert OP.kind_of("v2cast-ch_tang_yao") == "face" and OP.kind_of("v2cast-sk_white_cyc") == "scene" and OP.wired("v2cast-sk_white_cyc")


def test_plan_skips_non_asset_gaps(root):
    story, looks = AJ.p1(root, RUN)
    assert AJ.plan_from_gap({"kind": "voice", "who": "路人甲", "what": "说话人不在人物表（P1 人物表 / 清单别名）里"}, story, looks, 1) is None
    assert AJ.plan_from_gap({"kind": "script", "who": "-", "what": "没有导入稿"}, story, looks, 1) is None
    p = AJ.plan_from_gap({"kind": "look", "who": "卓琳", "what": "卓琳 造型A 没有设定图"}, story, looks, 1)
    assert p["kind"] == "sheet" and p["id"] == "sheet-ch_zhuo_lin-A" and "全身" in p["spec"]["img"]
    p = AJ.plan_from_gap({"kind": "look", "who": "卓琳", "what": "卓琳 本镜造型对不上 P1 登记（script_match 0.00）"}, story, looks, 1)
    assert p["kind"] == "meta" and p["spec"]["op"] == "looks" and p["spec"]["look"] == "A"


# ------------------------------------------------------------------ 2）整轮：作业 → 候选 → 待办 → 选定 → 登记 → 就绪 → 阶段 B
def test_full_round_three_faces_one_scene_one_voice(root, monkeypatch):
    cfg = AW.config(root)
    check = fake_check(root)
    monkeypatch.setattr(AJ, "_checker", lambda: check)       # READY_HOOK 重跑就绪检查时也用夹具口径
    ln = FakeLanes()
    lanes = lambda c, in_use: [l for l in ("gpu36:0", "gpu36:1", "gpu33:0") if l not in in_use]   # noqa: E731
    spawn = make_spawn(root, cfg)
    # 第 1 拍：生成 8 个作业；meta 直接写入；两条道并行各起一个出图作业；音色链跑完
    r1 = AW.tick(root, cfg=cfg, spawn=spawn, lanes=lanes, check=check, ln=ln)
    assert sorted(r1["generated"][RUN]["created"])[:1] == ["face-ch_jiang_yubai"] and len(r1["generated"][RUN]["created"]) == 8
    assert {m["id"] for m in r1["meta"] if m.get("ok")} == {"meta-name-ch_zhuo_lin", "meta-name-ch_tang_yao", "meta-name-ch_jiang_yubai"}
    man = _j(root / "assets_v2/manifest.json")
    assert man["characters"]["ch_zhuo_lin"]["display_name"] == "卓琳"
    assert len([s for s in r1["started"] if s["lane"]]) == 2 and ln.held and all(b == AW.BY for _, b in ln.held)
    assert [s for s in r1["started"] if s["lane"] is None][0]["id"] == "voice-ch_zhuo_lin"
    assert "gpu33:2" not in {s["lane"] for s in r1["started"]}
    # 第 2 拍：收尸释放道，再派剩下的两个出图作业
    r2 = AW.tick(root, cfg=cfg, spawn=spawn, lanes=lanes, check=check, ln=ln)
    assert len(ln.released) >= 2 and all(k == "hold" and b == AW.BY for _, b, k in ln.released)
    assert len(r2["started"]) == 2
    AW.tick(root, cfg=cfg, spawn=spawn, lanes=lanes, check=check, ln=ln)
    jobs = {j["id"]: j for j in AJ.list_jobs(root, RUN)}
    waiting = [k for k, j in jobs.items() if j["state"] == "awaiting_pick"]
    assert sorted(waiting) == ["face-ch_jiang_yubai", "face-ch_tang_yao", "face-ch_zhuo_lin", "scene-sk_white_cyc", "voice-ch_zhuo_lin"]
    reqs = {r["id"]: r for r in _j(root / "data/owner_queue/requests.json")}
    assert set(reqs) == {"pick:face:ch_zhuo_lin", "pick:face:ch_tang_yao", "pick:face:ch_jiang_yubai", "pick:scene:sk_white_cyc", "pick:voice_v2:zhuo_lin"}
    fr = reqs["pick:face:ch_zhuo_lin"]
    assert len(fr["candidates"]) == 2 and all(c["contract_ok"] and c["thumb"] and c["file"].endswith(".png") for c in fr["candidates"])
    assert "点“用这个”就选定" in fr["detail"] and fr["run"] == RUN and fr["job"] == "face-ch_zhuo_lin"
    assert reqs["pick:voice_v2:zhuo_lin"]["candidates"][0]["audio"].endswith("zhuo_lin_a_sample.wav")
    assert not (root / "data/pipeline/asset_jobs" / RUN / "golden-ep01.json").is_file()
    # 项目方逐条选定（统一入口 owner_pick.process；push 关着）
    for rid, choice in (("pick:face:ch_zhuo_lin", "s1100"), ("pick:face:ch_tang_yao", "s1100"), ("pick:face:ch_jiang_yubai", "s1101"),
                        ("pick:scene:sk_white_cyc", "s1100"), ("pick:voice_v2:zhuo_lin", "b")):
        OP.accept(root, rid, choice, "", "fred")
        row = OP.process(root, rid, choice, "fred")
        assert row["state"] == "done", (rid, row.get("error"))
    man = _j(root / "assets_v2/manifest.json")
    face = man["characters"]["ch_zhuo_lin"]["face"]
    assert face["file"].startswith("assets_v2/characters/ch_zhuo_lin/face/") and (root / face["file"]).is_file()
    assert face["sha256"] == _sha((root / face["file"]).read_bytes()) and face["picked_by"] == "fred" and len(face["candidates_archived"]) == 1
    assert man["characters"]["ch_jiang_yubai"]["face"]["file"].endswith("_s1101.png")
    assert man["scenes"]["sk_white_cyc"]["base"]["file"].startswith("assets_v2/scenes/sk_white_cyc/")
    vc = _j(root / "config/voices_v2.json")
    assert vc["roles"]["zhuo_lin"]["selected"] == "b" and vc["cast_voice"]["map"]["ch_zhuo_lin"] == "zhuo_lin"
    # 登记后 READY_HOOK：作业 done、重跑就绪检查、全部就绪 → 只记“可交 producer”（W6 / L-151：不再生成 golden-epNN 作业）
    jobs = {j["id"]: j for j in AJ.list_jobs(root, RUN)}
    assert all(jobs[k]["state"] == "done" for k in waiting)
    assert jobs["face-ch_zhuo_lin"]["result"]["pick_id"] == "pick:face:ch_zhuo_lin"
    assert "golden-ep01" not in jobs and not (root / "data/pipeline/asset_jobs" / RUN / "golden-ep01.json").is_file()
    ready = _j(AJ.jobs_dir(root, RUN) / "_ready_ep01.json")
    assert ready["ready"] is True
    assert ready["golden"]["ready_for"] == "producer" and ready["golden"]["shots"] == [1, 2] and ready["golden"]["adult_skipped"] == [3]
    assert ready["golden"]["legacy_job"] is None
    r4 = AW.tick(root, cfg=cfg, spawn=spawn, lanes=lanes, check=check, ln=ln)
    assert r4["golden_pending"] == [] and not r4["started"]
    dec = [json.loads(l) for l in (root / "data/owner_queue/decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {d["id"] for d in dec} == set(reqs) and all(d["via"] == "owner_pick" for d in dec)


def test_register_refuses_second_face_and_bad_candidate(root):
    AJ.generate(RUN, 1, root, check=fake_check(root))
    f = root / "data/review_pages/x/a.png"
    _w(f, b"img-a")
    req = {"id": "pick:face:ch_tang_yao", "run": RUN, "episode": 1, "job": "face-ch_tang_yao",
           "candidates": [{"key": "a", "file": "data/review_pages/x/a.png", "contract_ok": True, "sha256": _sha(b"img-a")},
                          {"key": "bad", "file": "data/review_pages/x/none.png", "contract_ok": True}, {"key": "nc", "file": "data/review_pages/x/a.png", "contract_ok": False}]}
    with pytest.raises(AJ.RegisterError, match="没过契约"):
        AJ.register_pick(root, "face", req, "nc", "fred", push=False)
    with pytest.raises(AJ.RegisterError, match="不存在"):
        AJ.register_pick(root, "face", req, "bad", "fred", push=False)
    res = AJ.register_pick(root, "face", req, "a", "fred", push=False)
    assert res["archived"] == ["bad", "nc"] and _j(root / "assets_v2/manifest.json")["characters"]["ch_tang_yao"]["display_name"] == "唐瑶"
    again = AJ.register_pick(root, "face", req, "a", "fred", push=False)          # W-PICK 11-07：点的就是现在这张 = 确认（不再报“已经有”）
    assert again["noop"] == "已是这张" and again["confirmed"] and again["file"] == res["file"]
    _w(root / "data/review_pages/x/b.png", b"img-b")
    with pytest.raises(AJ.RegisterError, match="只有项目方本人能换"):           # 系统不能覆盖项目方登记的脸
        AJ.register_pick(root, "face", {**req, "candidates": [{"key": "b", "file": "data/review_pages/x/b.png", "contract_ok": True}]}, "b", AJ.AUTO_BY, push=False)
    with pytest.raises(AJ.RegisterError, match="不是 scene 类"):
        AJ.register_pick(root, "scene", req, "a", "fred", push=False)


def test_push_failure_is_recorded_not_rolled_back(root, monkeypatch):
    _w(root / "config/pipeline/asset_worker.json", {"push": True})
    _w(root / "data/review_pages/x/s.png", b"scene")
    req = {"id": "pick:scene:sk_white_cyc", "run": RUN, "episode": 1, "candidates": [{"key": "1", "file": "data/review_pages/x/s.png", "contract_ok": True}]}
    calls = []

    def pusher(r, host, rels):
        calls.append((host, tuple(rels)))
        if host == "gpu33":
            raise RuntimeError("rc=255 主连接断了")
        return {"ok": True, "sha": {x: "ab" for x in rels}}
    res = AJ.register_pick(root, "scene", req, "1", "fred", pusher=pusher)
    assert res["push"]["gpu36"]["ok"] and res["push"]["gpu33"]["ok"] is False and "255" in res["push"]["gpu33"]["error"]
    assert {h for h, _ in calls} == {"gpu33", "gpu36"} and all("assets_v2/manifest.json" in rels for _, rels in calls)
    assert _j(root / "assets_v2/manifest.json")["scenes"]["sk_white_cyc"]["base"]["file"]
    issues = (root / "data/pipeline/issues.jsonl").read_text(encoding="utf-8")
    assert "推送 gpu33 失败" in issues and "ASSET-WORKER" in issues


def test_worker_failed_job_retries_then_reports(root):
    cfg = AW.config(root)
    check = fake_check(root)
    ln = FakeLanes()

    def bad_render(job, lane, seed, _root):
        raise RuntimeError("ComfyUI 连不上")

    def spawn(job, jp, lane):
        if job["kind"] == "voice":
            AW.run_voice(jp, root, runner=lambda a: SimpleNamespace(returncode=1, stdout="", stderr="design 挂了"), remote_ready=lambda *a: True, cfg=cfg)
        else:
            AW.run_job(jp, lane, root, renderer=bad_render, cfg=cfg)
        return SimpleNamespace(pid=0, poll=lambda: 0)
    lanes = lambda c, in_use: ["gpu36:0", "gpu36:1"]   # noqa: E731
    for _ in range(6):
        AW.tick(root, cfg=cfg, spawn=spawn, lanes=lanes, check=check, ln=ln)
    jobs = {j["id"]: j for j in AJ.list_jobs(root, RUN)}
    assert jobs["face-ch_zhuo_lin"]["state"] == "failed" and jobs["face-ch_zhuo_lin"]["attempts"] == 2 and "ComfyUI" in jobs["face-ch_zhuo_lin"]["error"]
    assert jobs["voice-ch_zhuo_lin"]["state"] == "failed" and "design 挂了" in jobs["voice-ch_zhuo_lin"]["error"]
    assert "连续失败" in (root / "data/pipeline/issues.jsonl").read_text(encoding="utf-8")


def test_switches_off_only_generate(root):
    _w(root / "config/pipeline/asset_worker.json", {"apply_meta": False, "render": False, "voice": False})
    cfg = AW.config(root)
    r = AW.tick(root, cfg=cfg, spawn=lambda *a: pytest.fail("开关关着不许起子进程"), lanes=lambda *a: ["gpu36:0"], check=fake_check(root), ln=FakeLanes())
    assert len(r["generated"][RUN]["created"]) == 8 and not r["started"] and all(m.get("skipped") for m in r["meta"])
    assert sorted(r["render_waiting"]) == ["face-ch_jiang_yubai", "face-ch_tang_yao", "face-ch_zhuo_lin", "scene-sk_white_cyc"] and r["voice_waiting"] == ["voice-ch_zhuo_lin"]
    assert _j(root / "assets_v2/manifest.json")["characters"].keys() == {"lead_f"}
    r2 = AW.tick(root, cfg=cfg, dry=True, check=fake_check(root), ln=FakeLanes())
    assert not r2["started"]
    bad = AW.config(root / "nowhere")
    assert bad["_config_error"] and not bad["render"] and not bad["apply_meta"]


def test_worker_single_instance_lock(root, monkeypatch):
    assert AW.acquire_lock(root)
    assert AW.acquire_lock(root) is True                      # 同一进程再拿 = 接管自己的锁
    AW.release_lock(root)
    _w(AW.lock_path(root), json.dumps({"pid": 424242}).encode())
    monkeypatch.setattr(AW, "_pid_alive", lambda pid: pid == 424242)
    r = AW.tick(root, cfg=AW.config(root), check=fake_check(root), ln=FakeLanes())
    assert "worker.lock" in r["skipped"] and not r["runs"]
    monkeypatch.setattr(AW, "_pid_alive", lambda pid: False)   # 锁主进程死了 = 接管
    r = AW.tick(root, cfg=AW.config(root), check=fake_check(root), ln=FakeLanes(), spawn=lambda *a: SimpleNamespace(pid=0, poll=lambda: 0), lanes=lambda *a: [])
    assert r["runs"][RUN]["episode"] == 1 and not AW.lock_path(root).is_file()


def test_active_runs_only_advance_statuses(root):
    assert AW.active_runs(root) == {RUN: 1}


# ------------------------------------------------------------------ 3）设定候选模式（preflight）与 Q9 口径、合并看图解析
def _items(req):
    return {i.id: i for i in PF.check(req).items}


def test_preflight_setting_candidate_mode_waives_by_rule():
    rec = {"slots": [], "characters": [{"character": "ch_x", "name": "甲", "presence": "在画"}], "primary": "ch_x", "capacity": 4,
           "missing": [{"character": "甲", "kind": "身份脸缺图", "detail": "甲 没有登记身份脸部参考"},
                       {"character": "甲", "kind": "造型未登记", "detail": "甲 本镜造型对不上 P1 登记"}]}
    base = {"kind": "image", "cast": [{"name": "甲", "presence": "在画", "x": "中"}], "prompt": "x", "refs": [], "asset_refs": rec, "compiled_by": "ns_agent.compiler",
            "project": None, "framing_project": None, "loras": []}
    normal = _items(base)
    assert normal["I2"].status == "fail" and normal["I3"].status == "fail"
    face = _items({**base, "mode": "setting_candidate", "asset_stage": "face"})
    assert face["I2"].status == "na" and face["I3"].status == "na" and face["I2"].evidence["original_status"] == "fail"
    assert "设定候选模式" in face["I2"].detail and "原判" in face["I2"].detail
    scene = _items({**base, "mode": "setting_candidate", "asset_stage": "scene"})
    assert scene["I2"].status == "fail" and scene["I3"].status == "fail"            # scene 只豁免 I5
    unknown = PF.check({**base, "mode": "setting_candidate", "asset_stage": "logo"})
    assert any(i.id == "I2" and "失败关闭" in i.detail for i in unknown.blocking)
    nomode = _items({**base, "asset_stage": "face"})                                 # 只写 asset_stage 不写 mode = 不生效
    assert nomode["I2"].status == "fail"


def test_q9_asset_ignores_eye_contact_for_face_but_not_underage():
    post = {"items": [{"id": "Q9", "title": "本地看图复核", "status": "fail", "detail": "看镜头", "evidence": {"defects": ["eye_contact"]}}]}
    r = AC.q9_asset(post, "face")
    q9 = next(i for i in r["items"] if i["id"] == "Q9")
    assert q9["status"] == "pass" and q9["evidence"]["ignored_defects"] == ["eye_contact"] and q9["evidence"]["asset_stage"] == "face"
    post2 = {"items": [{"id": "Q9", "title": "t", "status": "fail", "detail": "x", "evidence": {"defects": ["eye_contact", "underage_look"]}}]}
    assert next(i for i in AC.q9_asset(post2, "face")["items"] if i["id"] == "Q9")["status"] == "fail"
    post3 = {"items": [{"id": "Q9", "title": "t", "status": "fail", "detail": "x", "evidence": {"defects": ["eye_contact"]}}]}
    assert next(i for i in AC.q9_asset(post3, "scene")["items"] if i["id"] == "Q9")["status"] in ("fail", "na")   # 场景不豁免看镜头
    un = {"items": [{"id": "Q9", "title": "t", "status": "untested", "detail": "没结果", "evidence": {}}]}
    assert next(i for i in AC.q9_asset(un, "face")["items"] if i["id"] == "Q9")["status"] == "untested"


def test_parse_bundle_items_age_ocr():
    text = "1. 符合：只有一个人\n2、不符合：看起来像学生\n3） 符合\n年龄：像未成年，脸很稚嫩\n文字：无\n总结：有不符合"
    p = AC.parse_bundle(text, 3)
    assert [x["ok"] for x in p["items"]] == [True, False, True] and p["age"]["status"] == "fail" and p["ocr"]["status"] == "pass"
    p2 = AC.parse_bundle("1. 符合\n年龄：成年\n文字：右下角有 LOGO 字样\n总结：全部符合", 2)
    assert p2["items"][1]["text"] == "（没答）" and p2["age"]["status"] == "pass" and p2["ocr"]["status"] == "fail"
    assert AC.parse_bundle("", 1)["age"]["status"] == "untested"


def test_vlm_items_cover_person_age_and_scene_without_person():
    items, person = AW.vlm_items({"kind": "face", "spec": {"sex": "女性", "age": 35}})
    assert person and any("成年人" in x for x in items) and any("只有一个人" in x for x in items)
    items, person = AW.vlm_items({"kind": "scene", "spec": {"space": "白幕", "light": "环形灯"}})
    assert not person and items[0] == "画面里没有人"


# ------------------------------------------------------------------ 4）接线：enqueue_pick、常驻服务、导入钩子、voice_v2 --roles-file
def test_enqueue_pick_replaces_same_id_and_fills_detail(root):
    OP.enqueue_pick(root, {"id": "pick:face:x", "title": "挑 x", "candidates": [{"key": "1", "label": "a", "contract_ok": True, "file": "data/x.png"}]})
    OP.enqueue_pick(root, {"id": "pick:face:x", "title": "挑 x 第二版", "candidates": [{"key": "2", "label": "b", "contract_ok": True, "file": "data/y.png"}]})
    rows = _j(root / "data/owner_queue/requests.json")
    assert len(rows) == 1 and rows[0]["title"] == "挑 x 第二版" and rows[0]["kind"] == "pick" and "点“用这个”就选定" in rows[0]["detail"]
    with pytest.raises(ValueError):
        OP.enqueue_pick(root, {"id": "pick:face:y", "candidates": []})


def test_resident_calls_asset_worker_each_tick(monkeypatch):
    RS = _load("autoflow_resident_t", "tools/factory/autoflow_resident.py")
    calls = []
    aw = SimpleNamespace(active_runs=lambda root: {"a": 1, "b": 2}, tick=lambda runs: calls.append(runs) or {"started": [{"id": "x"}], "meta": []})
    r = RS.asset_tick(["a"], aw=aw)
    assert calls == [{"a": 1}] and r == {"started": [{"id": "x"}]}
    assert RS.asset_tick(None, aw=SimpleNamespace(active_runs=lambda root: {}, tick=lambda runs: (_ for _ in ()).throw(RuntimeError("boom"))))["error"].startswith("RuntimeError")
    src = (ROOT / "tools/factory/autoflow_resident.py").read_text(encoding="utf-8")
    assert '"assets": asset_tick(runs)' in src.split("def tick(", 1)[1].split("\ndef ", 1)[0]
    assert AW.ADVANCE_STATUSES == RS.ADVANCE_STATUSES


def test_autoflow_import_hook_generates_jobs(monkeypatch, tmp_path):
    AF = _load("autoflow_hook_t2", "tools/script_rsi/autoflow.py")
    ER = _load("episode_ready_t2", "tools/master/episode_ready.py")
    RI = _load("report_issue_t2", "tools/master/report_issue.py")
    fake = {"ready": False, "gaps": [{"kind": "face", "who": "卓琳（ch_zhuo_lin）", "what": "没有身份脸", "owner": "资产线", "shots": [1]}], "shots": []}
    monkeypatch.setattr(ER, "check", lambda run, ep: fake)
    monkeypatch.setattr(RI, "report", lambda *a, **k: None)
    gen = []
    AJ2 = SimpleNamespace(generate=lambda run, ep, res=None, **k: gen.append((run, ep, res)) or {"ready": False, "created": ["face-ch_zhuo_lin"], "existing": [], "golden": None})
    monkeypatch.setattr(AF, "_load", lambda name, rel: {"episode_ready": ER, "report_issue": RI, "asset_jobs": AJ2}[name])

    class St:
        def __init__(self): self.d = {}; self.stages = {}
        def stage(self, k, *a, **kw): self.stages[k] = (a, kw)
        def set(self, **k): self.d.update(k)
    st = St()
    AF.ready_after_import("demo", 1, st)
    assert gen == [("demo", 1, fake)] and st.stages["asset_jobs"][1]["created"] == 1 and "卓琳" in st.d["next_action"]


def test_voice_v2_roles_file_adds_role(tmp_path):
    V2 = _load("voice_v2_t", "tools/v2style/voice_v2.py")
    rf = tmp_path / "r.json"
    _w(rf, {"zhuo_lin": {"label": "x"}, "new_role": {"label": "新", "gender": "male", "char_id": "ch_new", "persona": "p",
                                                     "cands": [["a", "普通话（标准）", "std", "male, 30"], ["b", "沪语", "wu", "男性"]]}})
    added = V2.load_roles_file(rf)
    assert added == ["new_role"] and V2.ROLES["new_role"]["cands"][0][2] == V2.REF_STD and V2.ROLES["new_role"]["cands"][1][2] == V2.REF_WU
    assert V2.ROLES["zhuo_lin"]["label"] != "x"         # 写死的角色不被覆盖


def test_voice_job_spec_and_roles_file(root):
    story, _ = AJ.p1(root, RUN)
    s = AJ.spec_voice(story, "ch_zhuo_lin")
    assert s["role"] == "zhuo_lin" and s["gender"] == "female" and len(s["cands"]) == 3 and "crisp bright alto" in s["cands"][0][3]
    p = AW.voice_roles_file(root, {"run": RUN, "id": "voice-ch_zhuo_lin", "spec": s})
    assert _j(p)["zhuo_lin"]["char_id"] == "ch_zhuo_lin"


def test_cast_v2_uses_official_mode():
    src = (ROOT / "tools/promptfix/cast_v2.py").read_text(encoding="utf-8")
    assert 'mode="setting_candidate"' in src and 'r.startswith(("I2 ", "I3 "))' not in src
    src2 = (ROOT / "tools/pipeline/asset_worker.py").read_text(encoding="utf-8")
    assert 'mode="setting_candidate", asset_stage=job["kind"]' in src2



# ------------------------------------------------------------------ 5）AUTOFIX-O 11-03：OVERSIGHT-A 复审的 P0 / P1 / P2
def _adopt_cast_s(root, cid="ch_tang_yao", sha=False):
    f = root / f"data/review_pages/v2_cast/{cid}_s1.png"
    _w(f, f"cast-s-{cid}".encode())
    c = {"key": f"{cid}#1", "label": "候选1", "file": f"data/review_pages/v2_cast/{cid}_s1.png", "contract_ok": True}
    if sha:
        c["sha256"] = _sha(f.read_bytes())
    _w(root / "data/owner_queue/requests.json", [{"id": f"v2cast-{cid}", "kind": "pick", "title": "挑一张", "by": "CAST-S", "candidates": [c]}])
    AJ.generate(RUN, 1, root, check=fake_check(root))
    return _j(root / "data/owner_queue/requests.json")[0]


def test_register_legacy_pick_takes_run_from_job_never_current_run(root, monkeypatch):
    """ISS-1103-004546-a997：旧式 v2cast-* 没有 run 字段 → 从作业取 run；当前剧是 V1 也不回退过去"""
    runs = _j(root / "config/pipeline/runs.json")
    runs["primary"] = "series10_v1"
    runs["runs"]["series10_v1"] = {"status": "archived"}
    _w(root / "config/pipeline/runs.json", runs)
    monkeypatch.setenv("NS_RUN", "series10_v1")
    req = _adopt_cast_s(root)
    assert "run" not in req
    res = AJ.register_pick(root, "face", req, "ch_tang_yao#1", "fred", push=False)
    assert res["run"] == RUN and res["job"] == "face-ch_tang_yao"
    face = _j(root / "assets_v2/manifest.json")["characters"]["ch_tang_yao"]["face"]
    assert face["sha256"] == _sha((root / face["file"]).read_bytes()) and face["sha256_source"] == "computed_at_register"   # 旧式候选没 sha：先算再登记
    # 找不到作业、请求也没 run → 失败关闭（不猜剧）
    with pytest.raises(AJ.RegisterError, match="不回退"):
        AJ.register_pick(root, "scene", {"id": "v2cast-sk_nowhere", "candidates": req["candidates"]}, "ch_tang_yao#1", "fred", push=False)
    # 请求写的 run 与作业不一致 → 拒绝
    with pytest.raises(AJ.RegisterError, match="找不到|不一致"):
        AJ.register_pick(root, "face", {**req, "run": "series10_v1"}, "ch_tang_yao#1", "fred", push=False)


def test_owner_pick_replay_registers_legacy_cast_s_picks(root, monkeypatch):
    """端到端：CAST-S 旧式条目 + 项目方经旧入口的选择 → replay 用作业的 run 登记，作业 done"""
    monkeypatch.setattr(AJ, "_checker", lambda: fake_check(root))
    req = _adopt_cast_s(root, "ch_zhuo_lin")
    from ns_api import owner_queue as OQ
    OQ._record(root, {"id": req["id"], "kind": "pick", "choice": "ch_zhuo_lin#1", "by": "fred", "source": "CAST-S"})
    out = OP.replay(root)
    assert [(x["id"], x["state"]) for x in out] == [("v2cast-ch_zhuo_lin", "done")], out
    man = _j(root / "assets_v2/manifest.json")["characters"]["ch_zhuo_lin"]
    assert man["face"]["file"].startswith("assets_v2/characters/ch_zhuo_lin/face/") and man["display_name"] == "卓琳"
    assert AJ.load_job(AJ.job_path(root, RUN, "face-ch_zhuo_lin"))["state"] == "done"


def test_find_job_by_pick_filters_run_and_skips_unregistered(root):
    """ISS-1103-004549-cb05：试跑剧（没登记）的同名作业不参与匹配；给了 run 只看那一部"""
    AJ.generate(RUN, 1, root, check=fake_check(root))
    _w(root / "data/pipeline/asset_jobs/aaa_trial/face-ch_zhuo_lin.json", {"id": "face-ch_zhuo_lin", "run": "aaa_trial", "pick_id": "pick:face:ch_zhuo_lin"})
    assert AJ.find_job_by_pick(root, "pick:face:ch_zhuo_lin")["run"] == RUN
    assert AJ.find_job_by_pick(root, "pick:face:ch_zhuo_lin", run=RUN)["run"] == RUN
    assert AJ.find_job_by_pick(root, "pick:face:ch_zhuo_lin", run="aaa_trial") is None


def test_trial_runs_cannot_write_real_repo():
    """ISS-1103-004549-cb05：真实仓库里只认 runs.json 登记的剧；测试里起真实子进程 = 直接报错；子进程按作业所在数据根干活"""
    assert RUN not in AJ.registered_runs(AJ.ROOT)
    before = sorted(p.name for p in AJ.jobs_dir(AJ.ROOT, RUN).glob("*")) if AJ.jobs_dir(AJ.ROOT, RUN).is_dir() else None
    with pytest.raises(AJ.TrialRunInRealRepo):
        AJ.save_job(AJ.ROOT, {"id": "x", "run": RUN})
    with pytest.raises(AJ.TrialRunInRealRepo):
        AJ.generate(RUN, 1, AJ.ROOT, res={"ready": False, "gaps": []})
    after = sorted(p.name for p in AJ.jobs_dir(AJ.ROOT, RUN).glob("*")) if AJ.jobs_dir(AJ.ROOT, RUN).is_dir() else None
    assert after == before                                              # 一个文件都没写进真实仓库
    with pytest.raises(RuntimeError, match="测试里不许"):
        AW._spawn({"id": "x", "run": RUN, "kind": "face"}, AJ.ROOT / "data/pipeline/asset_jobs" / RUN / "x.json", "gpu36:0")
    assert AW.root_of_job(Path("/tmp/r/data/pipeline/asset_jobs/demo/x.json")) == Path("/tmp/r").resolve()
    with pytest.raises(RuntimeError):
        AW.root_of_job(Path("/tmp/r/x.json"))


def test_real_data_guard_blocks_test_writes_into_real_asset_jobs():
    """conftest 的真实数据写保护覆盖 data/pipeline/asset_jobs 和 data/owner_queue：测试一旦写真实 data/ 当场失败"""
    import real_data_guard as RDG
    if not RDG._state["on"]:
        pytest.skip("写保护关着（NS_REAL_DATA_GUARD=off），不做真实路径探测")
    for rel in ("data/pipeline/asset_jobs/__guard_probe__/x.json", "data/owner_queue/__guard_probe__.json"):
        with pytest.raises(RDG.RealDataWriteError):
            (ROOT / rel).write_text("x", encoding="utf-8")
    RDG.VIOLATIONS[:] = [v for v in RDG.VIOLATIONS if "test_real_data_guard_blocks" not in v.get("test", "")]


def test_run_voice_skips_selected_role_and_refuses_real_chain_in_tmp(root):
    AJ.generate(RUN, 1, root, check=fake_check(root))
    jp = AJ.job_path(root, RUN, "voice-ch_zhuo_lin")
    with pytest.raises(RuntimeError, match="不是真实仓库"):
        AW.run_voice(jp, root, cfg=AW.config(root))                        # 没注入 runner = 真 voice_v2（写真实 config），临时目录里不许
    cfg = _j(root / "config/voices_v2.json")
    cfg["roles"]["zhuo_lin"] = {"selected": "c", "candidates": []}
    _w(root / "config/voices_v2.json", cfg)
    j = AW.run_voice(jp, root, runner=lambda a: pytest.fail("已选定不该再跑 voice_v2"), remote_ready=lambda *a: True, cfg=AW.config(root))
    assert j["state"] == "done" and "已选定" in j["result"]["skipped"]
    assert "zhuo_lin" not in _j(root / "config/voices_v2.json")["support_candidates"]["roles"]


def test_voice_v2_page_note_not_hardcoded():
    V2 = _load("voice_v2_note_t", "tools/v2style/voice_v2.py")
    assert "江予白" in V2.support_note([{"label": "江予白 · jiang_yubai（配角，待选）"}]) and "卓琳" not in V2.support_note([{"label": "江予白 · x"}])
    assert "都已选定" in V2.support_note([])
    src = (ROOT / "tools/v2style/voice_v2.py").read_text(encoding="utf-8")
    assert "卓琳、唐瑶两位" not in src


def test_sheet_waits_for_registered_face_and_i2_not_waived(root):
    """ISS-1103-004547-ca20：脸没登记 → sheet 不派；登记后才派；preflight sheet 不再豁免 I2"""
    story, looks = AJ.p1(root, RUN)
    plan = AJ.plan_from_gap({"kind": "look", "who": "卓琳", "what": "卓琳 造型A 没有设定图"}, story, looks, 1)
    job = AJ._new_job(RUN, 1, plan, {"who": "卓琳", "what": "卓琳 造型A 没有设定图"})
    AJ.save_job(root, job)
    cfg = {**AW.config(root), "apply_meta": False, "voice": False}
    started = []
    spawn = lambda j, jp, lane: started.append(j["id"]) or SimpleNamespace(pid=0, poll=lambda: None)   # noqa: E731
    noop = {"run": RUN, "episode": 1, "ready": False, "gaps": [{"kind": "look", "who": "卓琳", "what": "卓琳 造型A 没有设定图", "owner": "资产线"}]}
    r = AW.tick(root, cfg=cfg, spawn=spawn, lanes=lambda c, u: ["gpu36:0", "gpu36:1"], check=lambda run, ep: noop, ln=FakeLanes())
    assert r["sheet_waiting_face"] == ["sheet-ch_zhuo_lin-A"] and "sheet-ch_zhuo_lin-A" not in started
    assert AJ.registered_face(root, RUN, "ch_zhuo_lin") is None
    f = root / "data/review_pages/x/z.png"
    _w(f, b"zhuo-face")
    AJ.register_pick(root, "face", {"id": "pick:face:ch_zhuo_lin", "run": RUN, "candidates": [{"key": "a", "file": "data/review_pages/x/z.png", "contract_ok": True}]},
                     "a", "fred", push=False)
    face = AJ.registered_face(root, RUN, "ch_zhuo_lin")
    assert face and face["sha256"] == _sha(b"zhuo-face")
    r2 = AW.tick(root, cfg=cfg, spawn=spawn, lanes=lambda c, u: ["gpu36:0", "gpu36:1"], check=lambda run, ep: noop, ln=FakeLanes())
    assert "sheet-ch_zhuo_lin-A" in started and not r2.get("sheet_waiting_face")
    # 出图前核对：参考里必须有这张脸（按 sha）
    with pytest.raises(RuntimeError, match="没有已登记的身份脸"):
        AW.require_face_ref(root, job, {"refs": ["data/review_pages/x/none.png"], "compile_trace": {"refs": [{"file": "x", "sha": "deadbeef"}]}})
    assert AW.require_face_ref(root, job, {"refs": [face["file"]], "compile_trace": {"refs": [{"file": face["file"], "sha": face["sha256"][:16]}]}}) == face
    assert PF.ASSET_STAGE_WAIVE["sheet"] == ("I3", "I4")
    rec = {"slots": [], "characters": [{"character": "ch_x", "name": "甲", "presence": "在画"}], "primary": "ch_x", "capacity": 4,
           "missing": [{"character": "甲", "kind": "身份脸缺图", "detail": "甲 没有登记身份脸部参考"}]}
    base = {"kind": "image", "cast": [{"name": "甲", "presence": "在画", "x": "中"}], "prompt": "x", "refs": [], "asset_refs": rec,
            "compiled_by": "ns_agent.compiler", "project": None, "framing_project": None, "loras": [], "mode": "setting_candidate", "asset_stage": "sheet"}
    assert _items(base)["I2"].status == "fail"


def test_scene_uses_empty_suffix_time_light_from_p1(root):
    """ISS-1103-004550-8787：空镜后缀无人、时间光线取 P1、负面写明不出人；人像风格后缀整句换掉；I7 在空镜模式只认空镜后缀"""
    from ns_agent.gen_contract import style as ST
    story, _ = AJ.p1(root, RUN)
    sc = AJ.spec_scene(story, "sk_white_cyc")
    assert ST.EMPTY_SUFFIX in sc["suffix"] and "白天" in sc["suffix"] and "环形灯正面高亮" in sc["suffix"]
    for bad in ("闪光", "皮肤", "夜里", "人物被"):
        assert bad not in sc["suffix"] and bad not in sc["img"]
    assert "人物" in sc["negative"] and "皮肤" in sc["negative"]
    s2 = AJ.scene_suffix("日", "环形灯正面高亮，风机吹起发丝")
    assert "环形灯正面高亮" in s2 and "发丝" not in s2                    # 带人的半句不进空镜
    portrait = ST.run_suffixes("series10_v2")
    assert portrait, "series10_v2 应有分段风格后缀"
    jc = {"prompt": f"空镜，无人物，影棚白幕，{portrait[-1]}，{ST.NO_TEXT}", "framing_project": "series10_v2", "negative": ""}
    out = AW.empty_suffix(jc, sc)
    assert sc["suffix"] in out["prompt"] and portrait[-1] not in out["prompt"] and "人物被闪光" not in out["prompt"] and "人物" in out["negative"]
    with pytest.raises(RuntimeError, match="空镜后缀"):
        AW.empty_suffix(jc, {"suffix": "随便"})
    rec = {"slots": [], "characters": [], "primary": None, "capacity": 4, "missing": []}
    base = {"kind": "image", "cast": [], "refs": [], "asset_refs": rec, "compiled_by": "ns_agent.compiler", "project": None, "framing_project": None,
            "loras": [], "mode": "setting_candidate", "asset_stage": "scene"}
    assert _items({**base, "prompt": out["prompt"]})["I7"].status == "pass"
    assert _items({**base, "prompt": jc["prompt"]})["I7"].status == "fail"
    item = AJ.plan_from_gap({"kind": "item", "who": "卓琳", "what": "卓琳 造型A 的包“黑色手袋”没有图"}, story, [], 1)
    assert ST.EMPTY_SUFFIX in item["spec"]["suffix"] and "人物" in item["spec"]["negative"]


def test_spec_face_blocks_missing_age_and_drops_color_tone(root):
    story, looks = AJ.p1(root, RUN)
    s = AJ.spec_face(story, looks, "ch_zhuo_lin", 1)
    assert "酒红与黑" not in s["desc"] and "酒红与黑" not in s["img"] and "鲜红色长指甲" in s["desc"] and "薄唇" in s["desc"]
    c = AJ.p1_char(story, "ch_zhuo_lin")
    c.pop("age")
    with pytest.raises(RuntimeError, match="没有年龄"):
        AJ.spec_face(story, looks, "ch_zhuo_lin", 1)
    c["age"] = 30
    c["zh_look"] = "匀称｜黑发"
    with pytest.raises(RuntimeError, match="不是六段"):
        AJ.spec_face(story, looks, "ch_zhuo_lin", 1)
    c["zh_look"] = "匀称｜黑色齐肩直发｜酒红与黑｜鲜红色长指甲｜薄唇"           # 只缺年龄段：其余五段照对位
    assert "酒红与黑" not in AJ.spec_face(story, looks, "ch_zhuo_lin", 1)["desc"]


def test_setting_script_is_v2_neutral_shell(root):
    """L-126：设定候选外壳不再拿 V1 夹具；没有 V1 人物锁 / 风格句"""
    story, looks = AJ.p1(root, RUN)
    for kind, spec in (("face", AJ.spec_face(story, looks, "ch_zhuo_lin", 1)), ("scene", AJ.spec_scene(story, "sk_white_cyc"))):
        s = AW.script_for({"kind": kind, "spec": spec, "run": RUN, "id": f"{kind}-x"})
        dump = s.model_dump_json()
        for v1 in ("林晚", "顾沉", "徕卡", "lnwan01", "漆皮之下", "series10_v1"):
            assert v1 not in dump, (kind, v1)
        assert s.episodes[0].shots[0].img_prompt == spec["img"]
    for rel in ("tools/pipeline/asset_worker.py", "tools/promptfix/cast_v2.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert 'tests/fixtures/promptfix/frozen_v1_subset.json").read_text' not in src, rel


def test_startup_replay_runs_in_background_with_deadline(root, monkeypatch):
    """ISS-1103-004547-6260：启动事件不阻塞（后台守护线程）；到时限的条目留到下次（deferred，不占位）"""
    import threading
    import time as _t
    gate = threading.Event()
    orig = OP.replay
    monkeypatch.setattr(OP, "replay", lambda r, deadline=None, **k: gate.wait(5) and [])   # RESTARTFIX-O：replay 多了 via=
    t0 = _t.time()
    th = OP.start_replay_thread(root, timeout_s=1)
    assert _t.time() - t0 < 0.5 and th.daemon and th.is_alive()
    gate.set()
    th.join(5)
    monkeypatch.setattr(OP, "replay", orig)
    req = _adopt_cast_s(root, "ch_jiang_yubai")
    from ns_api import owner_queue as OQ
    OQ._record(root, {"id": req["id"], "kind": "pick", "choice": "ch_jiang_yubai#1", "by": "fred"})
    out = OP.replay(root, deadline=_t.time() - 1)
    assert out[0]["state"] == "deferred" and OP.state_of(root, req["id"]) == {}
    src = (ROOT / "services/api/ns_api/owner_pick.py").read_text(encoding="utf-8")
    body = src.split("def _replay_on_startup", 1)[1].split("\n# ", 1)[0]
    call = "start_replay_thread(REPO, require_port=True)"      # RESTARTFIX-O：只在正式实例上、确认持有 :8800 后才补
    assert call in body and "replay(REPO" not in body.replace(call, "")


def test_replay_retries_stale_placeholder_left_by_dead_process(root, monkeypatch):
    """11-03 00:59：一次补执行进程中途没了，条目停在 accepted（replay=true）；超过 stale_s 的占位要能重补，新鲜的不动"""
    monkeypatch.setattr(AJ, "_checker", lambda: fake_check(root))
    req = _adopt_cast_s(root, "ch_tang_yao")
    from ns_api import owner_queue as OQ
    OQ._record(root, {"id": req["id"], "kind": "pick", "choice": "ch_tang_yao#1", "by": "fred"})
    OP._set_state(root, req["id"], state="accepted", choice="ch_tang_yao#1", by="fred", replay=True)
    assert OP.replay(root) == []                                         # 刚占位（可能有人正在处理）→ 不重补
    out = OP.replay(root, stale_s=0)
    assert [(x["id"], x["state"]) for x in out] == [(req["id"], "done")], out
    assert _j(root / "assets_v2/manifest.json")["characters"]["ch_tang_yao"]["face"]["file"]
    assert OP.replay(root, stale_s=0) == []                              # done 永远不重补


def test_require_face_ref_uses_full_sha_of_sent_files_even_with_hash_in_name(root):
    """11-03 01:14：compile_trace.refs[].sha 是 16 位短 sha，和清单完整 sha 比永远不等 → 三条 sheet 全失败。
    改成按实际送进去的参考文件算完整 sha；真实格式文件名（带 #）也要过"""
    f = root / "data/review_pages/x/z.png"
    _w(f, b"zhuo-face")
    AJ.register_pick(root, "face", {"id": "pick:face:ch_zhuo_lin", "run": RUN, "candidates": [{"key": "a", "file": "data/review_pages/x/z.png", "contract_ok": True}]},
                     "a", "fred", push=False)
    mp = root / "assets_v2/manifest.json"
    man = _j(mp)
    old = man["characters"]["ch_zhuo_lin"]["face"]["file"]
    legacy = old.rsplit("/", 1)[0] + "/ch_zhuo_lin_face_ch_zhuo_lin#3.png"         # 11-03 登记进去的真实文件名格式
    _w(root / legacy, (root / old).read_bytes())
    man["characters"]["ch_zhuo_lin"]["face"]["file"] = legacy
    _w(mp, man)
    job = {"run": RUN, "spec": {"cid": "ch_zhuo_lin"}}
    face = AW.require_face_ref(root, job, {"refs": [legacy], "compile_trace": {"refs": [{"file": legacy, "sha": _sha(b"zhuo-face")[:16]}]}})
    assert face["file"] == legacy
    with pytest.raises(RuntimeError, match="没有已登记的身份脸"):
        AW.require_face_ref(root, job, {"refs": [], "compile_trace": {"refs": [{"file": legacy, "sha": _sha(b"zhuo-face")[:16]}]}})


@pytest.mark.real_data
def test_real_sheet_compile_sends_registered_face():
    """真实数据（只读）：series10_v2 卓琳造型 A 的设定图编译 → 参考里有已登记身份脸，require_face_ref 通过"""
    run = "series10_v2"
    face = AJ.registered_face(AJ.ROOT, run, "ch_zhuo_lin")
    if not face or not AJ.job_path(AJ.ROOT, run, "sheet-ch_zhuo_lin-A").is_file():
        pytest.skip("真实清单里卓琳还没登记身份脸 / 没有 sheet 作业")
    job = AJ.load_job(AJ.job_path(AJ.ROOT, run, "sheet-ch_zhuo_lin-A"))
    import os
    old = os.environ.get("NS_RUN")
    try:
        jc = AW._compile(job, AJ.ROOT)                       # 内部已调 require_face_ref，不过就抛
    finally:
        if old is None:
            os.environ.pop("NS_RUN", None)
        else:
            os.environ["NS_RUN"] = old
    assert face["file"] in jc["refs"]


def test_register_uses_safe_file_names_and_normalize_migrates(root):
    """文件名只许 [A-Za-z0-9_.-]：候选 key 带 # 也登记成规范名；已登记的旧名迁移后 sha 不变、原件进隔离区、推两台"""
    assert AJ.safe_name("ch_zhuo_lin#3") == "ch_zhuo_lin_3" and AJ.safe_name("a b#c") == "a_b_c"
    req = _adopt_cast_s(root, "ch_tang_yao")
    AJ.register_pick(root, "face", req, "ch_tang_yao#1", "fred", push=False)
    f = _j(root / "assets_v2/manifest.json")["characters"]["ch_tang_yao"]["face"]
    assert f["file"].endswith("ch_tang_yao_face_ch_tang_yao_1.png") and "#" not in f["file"]
    # 模拟 11-03 已登记的旧名
    man = _j(root / "assets_v2/manifest.json")
    legacy = "assets_v2/scenes/sk_white_cyc/sk_white_cyc_base_sk_white_cyc#2.png"
    _w(root / legacy, b"scene-bytes")
    man["scenes"]["sk_white_cyc"] = {"base": {"file": legacy, "sha256": _sha(b"scene-bytes")}}
    _w(root / "assets_v2/manifest.json", man)
    _w(root / "config/pipeline/asset_worker.json", {"push": True})
    pushed = []
    out = AJ.normalize_names(root, RUN, pusher=lambda r, host, rels: pushed.append((host, tuple(rels))) or {"ok": True})
    assert out["renamed"] == [(legacy, "assets_v2/scenes/sk_white_cyc/sk_white_cyc_base_sk_white_cyc_2.png")]
    b = _j(root / "assets_v2/manifest.json")["scenes"]["sk_white_cyc"]["base"]
    assert b["sha256"] == _sha(b"scene-bytes") == _sha((root / b["file"]).read_bytes()) and b["renamed_from"] == legacy
    assert not (root / legacy).exists() and (root / out["quarantine"] / legacy).is_file()
    assert {h for h, _ in pushed} == {"gpu33", "gpu36"} and all(b["file"] in rels and "assets_v2/manifest.json" in rels for _, rels in pushed)
    assert AJ.normalize_names(root, RUN, push=False)["renamed"] == []                       # 幂等


def test_requeue_resets_failed_job_only(root):
    AJ.generate(RUN, 1, root, check=fake_check(root))
    j = AJ.load_job(AJ.job_path(root, RUN, "face-ch_zhuo_lin"))
    with pytest.raises(RuntimeError, match="只有 failed"):
        AJ.requeue(root, RUN, "face-ch_zhuo_lin")
    j.update(state="failed", attempts=2, final=True, error="x")
    AJ.save_job(root, j)
    assert AJ.requeue(root, RUN, "face-ch_zhuo_lin", "根因已修") == {"id": "face-ch_zhuo_lin", "state": "pending", "attempts": 0}
    j = AJ.load_job(AJ.job_path(root, RUN, "face-ch_zhuo_lin"))
    assert j["final"] is False and j["error"] is None and "重新排队" in j["log"][-1] and (AJ.jobs_dir(root, RUN) / "_recheck").is_file()


def test_resident_loop_survives_exceptions_and_logs_exit_reason(tmp_path, monkeypatch):
    """01:16:52 resident 静默退出：主循环任何一拍异常都记进生命日志 + 心跳后继续；退出必留原因；asset_tick 出错也记一笔"""
    RS = _load("autoflow_resident_life_t", "tools/factory/autoflow_resident.py")
    monkeypatch.setattr(RS, "LIFELOG", tmp_path / "life.log")
    monkeypatch.setattr(RS, "HEARTBEAT", tmp_path / "hb.json")
    seq = iter([RuntimeError("boom"), {"runs": ["r"], "started": [], "assets": {"error": "AttributeError('x')"}}, {"runs": ["r"], "started": ["r ep01"], "assets": {}}])

    def tick(procs):
        v = next(seq)
        if isinstance(v, Exception):
            raise v
        return v
    assert RS.run_loop(1, False, tick_fn=tick, sleep=lambda s: None, max_ticks=3) == 0
    log = (tmp_path / "life.log").read_text(encoding="utf-8")
    assert "第 1 拍异常（已继续）" in log and "boom" in log and "asset_tick 出错" in log and "退出：" in log and "共 3 拍" in log
    assert _j(tmp_path / "hb.json")["last_started"] == ["r ep01"]

    def die(procs):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        RS.run_loop(1, False, tick_fn=die, sleep=lambda s: None)
    assert "退出：KeyboardInterrupt" in (tmp_path / "life.log").read_text(encoding="utf-8")


def test_resident_detach_breaks_away_and_restart_script_stops_only_locked_pid(tmp_path, monkeypatch):
    import subprocess
    RS = _load("autoflow_resident_detach_t", "tools/factory/autoflow_resident.py")
    monkeypatch.setattr(RS, "LIFELOG", tmp_path / "life.log")
    seen = {}

    def popen(cmd, **kw):
        seen.update(kw, cmd=cmd)
        return SimpleNamespace(pid=4242)
    monkeypatch.setattr(RS, "ROOT", tmp_path)
    assert RS.detach(30, popen=popen) == 4242
    if sys.platform == "win32":
        assert seen["creationflags"] & subprocess.CREATE_BREAKAWAY_FROM_JOB and seen["creationflags"] & subprocess.DETACHED_PROCESS
    assert "--interval" in seen["cmd"] and "--detach" not in seen["cmd"]
    ps1 = (ROOT / "ops/restart_autoflow.ps1").read_text(encoding="utf-8-sig")
    assert "CommandLine -match" not in ps1 and "--detach" in ps1 and "taskkill /PID $old" in ps1     # K-OPS-F30：只停锁里记的 pid


def test_v2_asset_file_serves_registered_scene_base():
    """scenes[sid].base 也是登记文件（以前漏了 → /api/v2/asset-file 404）"""
    from ns_api import v2_assets as V2
    man = {"characters": {"c": {"face": {"file": "assets_v2/characters/c/face/c_face_1.png"}}},
           "scenes": {"sk_x": {"base": {"file": "assets_v2/scenes/sk_x/sk_x_base_2.png"}}}}
    reg = V2.registered_files(man)
    assert reg == {"assets_v2/characters/c/face/c_face_1.png": False, "assets_v2/scenes/sk_x/sk_x_base_2.png": False}


def _sheet_png(path: Path):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (400, 800), (180, 180, 180))
    d = ImageDraw.Draw(im)
    d.rectangle([150, 60, 250, 140], fill=(230, 190, 170))      # 头
    d.rectangle([120, 140, 280, 640], fill=(120, 20, 40))       # 酒红套装
    d.rectangle([140, 640, 260, 760], fill=(20, 20, 20))        # 鞋 / 腿
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def _register_sheet(root, monkeypatch):
    monkeypatch.setattr(AJ, "_checker", lambda: fake_check(root))
    f = root / "data/review_pages/x/zf.png"
    _w(f, b"zhuo-face")
    AJ.register_pick(root, "face", {"id": "pick:face:ch_zhuo_lin", "run": RUN, "candidates": [{"key": "a", "file": "data/review_pages/x/zf.png", "contract_ok": True}]},
                     "a", "fred", push=False)
    story, looks = AJ.p1(root, RUN)
    plan = AJ.plan_from_gap({"kind": "look", "who": "卓琳", "what": "卓琳 造型A 没有设定图"}, story, looks, 1)
    job = AJ._new_job(RUN, 1, plan, {"who": "卓琳", "what": "x"})
    job["state"] = "awaiting_pick"
    AJ.save_job(root, job)
    _sheet_png(root / "data/review_pages/x/sheet.png")
    req = {"id": job["pick_id"], "run": RUN, "job": job["id"], "episode": 1,
           "candidates": [{"key": "s1", "file": "data/review_pages/x/sheet.png", "contract_ok": True}]}
    res = AJ.register_pick(root, "sheet", req, "s1", "fred", push=False)
    AJ.after_pick(root, "sheet", res, check=fake_check(root))
    return res


def test_sheet_registration_spawns_item_jobs_from_p1_parts(root, monkeypatch):
    """总调度 11-03 定 A：sheet 豁免 I4；sheet 登记后按 P1_looks 部件自动生成 item 作业（先从设定图裁）"""
    assert "I4" in PF.ASSET_STAGE_WAIVE["sheet"] and "I2" not in PF.ASSET_STAGE_WAIVE["sheet"]
    res = _register_sheet(root, monkeypatch)
    jobs = {j["id"]: j for j in AJ.list_jobs(root, RUN) if j["kind"] == "item"}
    assert "item-ch_zhuo_lin-A-outfit1" in jobs and "item-ch_zhuo_lin-A-shoes1" in jobs
    sh = jobs["item-ch_zhuo_lin-A-shoes1"]["spec"]
    assert sh["crop"] and sh["from_sheet"] == {"file": res["file"], "sha256": res["sha256"]} and sh["zone"] == "feet" and sh["part_label"] == "黑色细高跟"
    assert jobs["item-ch_zhuo_lin-A-shoes1"]["pick_id"] == "pick:item:ch_zhuo_lin:A_shoes1"
    assert AJ.plan_items_from_sheet(root, RUN, "ch_zhuo_lin", "A", 1, {"file": res["file"], "sha256": res["sha256"]}) == []   # 幂等


def test_crop_passes_contract_registers_directly_and_maps_part(root, monkeypatch):
    _delegate(root, True)                                       # L-139：只有代选开着才自动选用
    _register_sheet(root, monkeypatch)
    jp = AJ.job_path(root, RUN, "item-ch_zhuo_lin-A-shoes1")
    j = AW.run_crop(jp, root, checker=lambda img, items: {"status": "pass", "ocr": {"status": "pass"}})
    assert j["state"] == "done" and j["result"]["auto"] and len(j["result"]["box"]) == 4
    it = _j(root / "assets_v2/manifest.json")["characters"]["ch_zhuo_lin"]["looks"]["A"]["items"]["A_shoes1"]
    assert it["slot"] == "shoes" and it["sha256"] == _sha((root / it["file"]).read_bytes()) and "纯裁剪" in it["note"] and "#" not in it["file"]
    ov = _j(root / "data/looks/item_map_overrides.json")
    assert ov[RUN]["ch_zhuo_lin"]["A"]["黑色细高跟"] == "A_shoes1"
    assert not any(r["id"] == "pick:item:ch_zhuo_lin:A_shoes1" for r in _j(root / "data/owner_queue/requests.json"))   # 不需要项目方挑
    box = j["result"]["box"]
    assert box[1] > 600                                                                 # 鞋 = 人物外框底部那一条


def test_crop_failure_falls_back_to_candidates(root, monkeypatch):
    _register_sheet(root, monkeypatch)
    jp = AJ.job_path(root, RUN, "item-ch_zhuo_lin-A-outfit1")
    j = AW.run_crop(jp, root, checker=lambda img, items: {"status": "fail", "ocr": {"status": "pass"}})
    assert j["state"] == "pending" and "没过契约" in j["spec"]["crop_failed"] and not AW.is_crop_job(j)
    started = []
    cfg = {**AW.config(root), "apply_meta": False, "voice": False, "max_parallel": 9}
    noop = {"run": RUN, "episode": 1, "ready": False, "gaps": []}
    AW.tick(root, cfg=cfg, spawn=lambda jj, p, lane: started.append((jj["id"], lane)) or SimpleNamespace(pid=0, poll=lambda: None),
            lanes=lambda c, u: [f"gpu36:{i}" for i in range(9) if f"gpu36:{i}" not in u], check=lambda r, e: noop, ln=FakeLanes())
    assert any(i == "item-ch_zhuo_lin-A-outfit1" and lane for i, lane in started)                                            # 改走出候选（借道出图）
    assert not any(i == "item-ch_zhuo_lin-A-acc1" for i, _ in started)                                                       # “饰品=无”不生成作业
    assert any(i == "item-ch_zhuo_lin-A-shoes1" and lane is None for i, lane in started)                                     # 还没裁的走 CPU 裁图


def test_q9_contradiction_only_on_ignored_defect_is_rejudged():
    """01:49：sheet 候选 Q9 全是 untested——看图模型只在 eye_contact（sheet 不判）上结论与证据矛盾；该项本就不判，按其余缺陷重判"""
    post = {"items": [{"id": "Q9", "title": "t", "status": "untested", "detail": "矛盾",
                       "evidence": {"defects": ["posed_stiff"], "contradiction": ["eye_contact"], "model": "Qwen3-VL-8B-Instruct"}}]}
    q = next(i for i in AC.q9_asset(post, "sheet")["items"] if i["id"] == "Q9")
    assert q["status"] in ("pass", "na") and "eye_contact" in q["evidence"]["ignored_defects"]
    q2 = next(i for i in AC.q9_asset(post, "scene")["items"] if i["id"] == "Q9")        # 场景要判看镜头：照旧 untested
    assert q2["status"] == "untested"
    post3 = {"items": [{"id": "Q9", "title": "t", "status": "untested", "evidence": {"defects": [], "contradiction": ["extra_hands"], "model": "m"}}]}
    assert next(i for i in AC.q9_asset(post3, "sheet")["items"] if i["id"] == "Q9")["status"] == "untested"


def test_stale_pending_jobs_close_when_gap_gone(root):
    """ISS-1103-011049-336c：缺口已经不在的 pending 作业自动收尾（meta-name 在登记脸时已写 display_name）；在跑 / 待选 / 设定图派生的不动"""
    AJ.generate(RUN, 1, root, check=fake_check(root))
    j = AJ.load_job(AJ.job_path(root, RUN, "face-ch_tang_yao"))
    j["state"] = "awaiting_pick"
    AJ.save_job(root, j)
    gaps = [g for g in fake_check(root)(RUN, 1)["gaps"] if g["kind"] != "name"]
    g = AJ.generate(RUN, 1, root, res={"ready": False, "gaps": gaps})
    assert sorted(g["closed"]) == ["meta-name-ch_jiang_yubai", "meta-name-ch_tang_yao", "meta-name-ch_zhuo_lin"]
    jm = AJ.load_job(AJ.job_path(root, RUN, "meta-name-ch_tang_yao"))
    assert jm["state"] == "done" and "缺口已不在" in jm["result"]["closed_reason"]
    assert AJ.load_job(AJ.job_path(root, RUN, "face-ch_tang_yao"))["state"] == "awaiting_pick"    # 待选的不动
    assert AJ.load_job(AJ.job_path(root, RUN, "face-ch_zhuo_lin"))["state"] == "pending"          # 缺口还在
    bad = [{"kind": "face", "who": "卓琳（ch_zhuo_lin）", "what": "没有身份脸", "owner": "资产线"}]
    story = _j(root / f"data/pipeline/runs/{RUN}/P1_storyline.json")
    next(c for c in story["characters"] if c["char_id"] == "ch_zhuo_lin").pop("age")
    _w(root / f"data/pipeline/runs/{RUN}/P1_storyline.json", story)
    g2 = AJ.generate(RUN, 1, root, res={"ready": False, "gaps": bad})                           # 同类缺口规划失败 → 这一类不收
    assert "face-ch_zhuo_lin" not in g2["closed"]


def test_sheet_checks_only_big_pieces_and_reject_reasons_are_written(root, monkeypatch):
    """总调度 11-03：设定图只核大件（上衣 / 外套 / 裤裙 / 鞋）；每张候选的拒因汇总进 error / log；Q9 排队超时 = 重排不算失败"""
    story, looks = AJ.p1(root, RUN)
    spec = AJ.spec_sheet(story, looks, "ch_zhuo_lin", "A", 1)
    spec["slots"] = {"服装": "驼色皮夹克、黑色工装裤", "鞋": "黑色短靴", "饰品": "右手腕缠两圈的黑色相机皮带"}
    items, _ = AW.vlm_items({"kind": "sheet", "spec": spec})
    line = next(x for x in items if x.startswith("大件穿着"))
    assert "驼色皮夹克" in line and "黑色短靴" in line and "相机皮带" not in line.split("（")[0]
    r = {"label": {"count": "pass", "q9": "pass", "prompt_vlm": "fail", "ocr": "pass"},
         "vlm": {"items": [{"n": 3, "ok": False, "text": "不符合，裤子是西裤"}]}, "postflight": {"items": []}}
    assert "prompt_vlm=fail" in AW.reject_reason(r) and "看图第3条" in AW.reject_reason(r)
    AJ.generate(RUN, 1, root, check=fake_check(root))
    jp = AJ.job_path(root, RUN, "face-ch_zhuo_lin")
    cfg = {**AW.config(root), "candidates": {"face": 1}}
    j = AW.run_job(jp, "gpu36:0", root, renderer=lambda job, lane, seed, _r: {**r, "seed": seed, "passed": False}, cfg=cfg)
    assert j["state"] == "failed" and "2 张不过" in j["error"] and "看图第3条" in j["error"]
    assert any("候选不过" in l for l in j["log"])

    def slow(job, lane, seed, _r):
        raise AW.Q9Timeout("排队超时")
    j2 = AJ.load_job(jp)
    j2.update(state="running", attempts=1)
    AJ.save_job(root, j2)
    j2 = AW.run_job(jp, "gpu36:0", root, renderer=slow, cfg=cfg)
    assert j2["state"] == "pending" and "排队超时" in j2["error"] and j2["attempts"] == 0
    post = {"items": [{"id": "Q9", "status": "untested", "detail": "没有本地看图复核结果（服务排队 / 未跑）", "evidence": {}}]}
    # L-196（项目方 11-05“全自动，不要检测那么多了”）：Q9 不在 gen_contract.blocking_items（Q1/count/text/adult）→ 没测出只记录、不排队重试（返回 False，状态记 na）
    monkeypatch.setattr(AW, "q9_blocking", lambda root=None: False)
    post_l196 = json.loads(json.dumps(post))
    assert AW.q9_queue_timeout(post_l196) is False
    assert post_l196["items"][0]["status"] == "na" and "L-196" in post_l196["items"][0]["status_recorded"]
    # Q9 回到硬闸（旧口径）时：没拿到看图结果 = 排队超时、要重试
    monkeypatch.setattr(AW, "q9_blocking", lambda root=None: True)
    assert AW.q9_queue_timeout(post) and not AW.q9_queue_timeout({"items": [{"id": "Q9", "status": "untested", "evidence": {"model": "m"}}]})


def test_sheet_auto_picks_best_and_owner_can_switch_with_downstream_redo(root, monkeypatch):
    """总调度 11-03：sheet / item 是派生资产 → 过检后按分数（身份余弦 + 看图通过率）自动登记最好的一张，inbox 只发“已自动选用，可修改”；
    项目方点别的候选 = 换成那张，下游单品作业自动重做。身份脸 / 场景 / 音色仍由项目方挑"""
    _delegate(root, True)                                       # L-139：只有代选开着才自动选用
    monkeypatch.setattr(AJ, "_checker", lambda: fake_check(root))
    f = root / "data/review_pages/x/zf.png"
    _w(f, b"zhuo-face")
    AJ.register_pick(root, "face", {"id": "pick:face:ch_zhuo_lin", "run": RUN, "candidates": [{"key": "a", "file": "data/review_pages/x/zf.png", "contract_ok": True}]},
                     "a", "fred", push=False)
    story, looks = AJ.p1(root, RUN)
    plan = AJ.plan_from_gap({"kind": "look", "who": "卓琳", "what": "卓琳 造型A 没有设定图"}, story, looks, 1)
    job = AJ._new_job(RUN, 1, plan, {"who": "卓琳", "what": "x"})
    AJ.save_job(root, job)
    sims = {1100: 0.70, 1101: 0.86}

    def render(job, lane, seed, _r):
        rd = AW.review_dir(root, job)
        p = rd / f"{job['id']}_s{seed}.png"
        _sheet_png(p)
        from PIL import Image, ImageDraw
        im = Image.open(p); ImageDraw.Draw(im).point((seed % 50, 5), fill=(0, 0, 0)); im.save(p)   # 两张内容不同
        rel = str(p.relative_to(root)).replace("\\", "/")
        return {"seed": seed, "passed": True, "label": {"q9": "pass"}, "review_file": rel, "thumb": rel, "sha256": _sha(p.read_bytes()), "file": rel,
                "postflight": {"items": [{"id": "Q1", "status": "pass", "evidence": {"sims": {"ch_zhuo_lin": sims[seed]}}}]},
                "vlm": {"items": [{"n": 1, "ok": True}, {"n": 2, "ok": True}]}}
    j = AW.run_job(AJ.job_path(root, RUN, job["id"]), "gpu36:0", root, renderer=render, cfg={**AW.config(root), "candidates": {"sheet": 2}})
    assert j["state"] == "done" and any("自动选用 s1101" in l for l in j["log"])
    sheet = _j(root / "assets_v2/manifest.json")["characters"]["ch_zhuo_lin"]["looks"]["A"]["sheet"]
    assert sheet["file"].endswith("_s1101.png") and sheet["picked_by"].startswith("系统自动")
    req = next(r for r in _j(root / "data/owner_queue/requests.json") if r["id"] == job["pick_id"])
    assert req["auto_picked"] == "s1101" and req["title"].startswith("已自动选用") and "可修改" in req["title"]
    assert AJ.load_job(AJ.job_path(root, RUN, "item-ch_zhuo_lin-A-shoes1"))["spec"]["from_sheet"]["file"] == sheet["file"]   # 下游已派
    assert job["pick_id"] not in OP.hidden_ids(root)                                    # 告知还在 inbox，可以改
    AW.run_crop(AJ.job_path(root, RUN, "item-ch_zhuo_lin-A-shoes1"), root, checker=lambda img, items: {"status": "pass", "ocr": {"status": "pass"}})
    # 项目方点“修改”换成另一张
    OP.accept(root, job["pick_id"], "s1100", "", "fred")
    row = OP.process(root, job["pick_id"], "s1100", "fred")
    assert row["state"] == "done", row.get("error")
    lk = _j(root / "assets_v2/manifest.json")["characters"]["ch_zhuo_lin"]["looks"]["A"]
    hist = lk["sheet"]["replaced"][0]
    assert lk["sheet"]["file"].endswith("_s1100.png") and hist["original_file"] == sheet["file"]
    assert hist["file"].startswith("data/_quarantine/") and (root / hist["file"]).is_file() and not (root / sheet["file"]).exists()   # 旧图隔离不删
    assert "A_shoes1" not in lk["items"] and lk["items_replaced"][0]["iid"] == "A_shoes1"
    ij = AJ.load_job(AJ.job_path(root, RUN, "item-ch_zhuo_lin-A-shoes1"))
    assert ij["state"] == "pending" and ij["spec"]["from_sheet"]["file"] == lk["sheet"]["file"] and AW.is_crop_job(ij)
    # 已登记的人工选择不许被系统覆盖（项目方本人改选见 test_w_pick_*）
    _w(root / "data/review_pages/x/zf2.png", b"zhuo-face-2")
    with pytest.raises(AJ.RegisterError, match="只有项目方本人能换"):
        AJ.register_pick(root, "face", {"id": "pick:face:ch_zhuo_lin", "run": RUN, "candidates": [{"key": "a", "file": "data/review_pages/x/zf2.png", "contract_ok": True}]},
                         "a", AJ.AUTO_BY, push=False)
    # L-198（11-05）：身份脸 / 场景底图也进代选（W-ASSETS 11-06）；仍只在代选开着时生效（deliver 查 delegate_active）
    assert "face" in AJ.AUTO_PICK_KINDS and "scene" in AJ.AUTO_PICK_KINDS


def test_tick_auto_picks_legacy_waiting_sheet_pick(root, monkeypatch):
    """规则上线前已投成“等项目方挑”的 sheet：下一拍按候选记录算分自动选用"""
    _delegate(root, True)                                       # L-139：只有代选开着才自动选用
    monkeypatch.setattr(AJ, "_checker", lambda: fake_check(root))
    _w(root / "data/review_pages/x/zf.png", b"zhuo-face")
    AJ.register_pick(root, "face", {"id": "pick:face:ch_zhuo_lin", "run": RUN, "candidates": [{"key": "a", "file": "data/review_pages/x/zf.png", "contract_ok": True}]},
                     "a", "fred", push=False)
    story, looks = AJ.p1(root, RUN)
    plan = AJ.plan_from_gap({"kind": "look", "who": "卓琳", "what": "卓琳 造型A 没有设定图"}, story, looks, 1)
    job = AJ._new_job(RUN, 1, plan, {"who": "卓琳", "what": "x"})
    job["state"] = "awaiting_pick"
    AJ.save_job(root, job)
    cands = []
    for seed, sim in ((1, 0.9), (2, 0.5)):
        p = root / f"data/review_pages/v2_assets/{RUN}/{job['id']}/{job['id']}_s{seed}.png"
        _sheet_png(p)
        _w(p.with_suffix(".json"), {"postflight": {"items": [{"id": "Q1", "evidence": {"sims": {"x": sim}}}]}, "vlm": {"items": [{"ok": True}]}})
        cands.append({"key": f"s{seed}", "label": f"候选 {seed}", "contract_ok": True, "file": str(p.relative_to(root)).replace("\\", "/")})
    AJ.post_pick(root, job, cands, "挑", "d")
    noop = {"run": RUN, "episode": 1, "ready": False, "gaps": [{"kind": "look", "who": "卓琳", "what": "卓琳 造型A 没有设定图", "owner": "资产线"}]}
    r = AW.tick(root, cfg={**AW.config(root), "render": False, "apply_meta": False, "voice": False}, check=lambda a, b: noop, ln=FakeLanes(),
                spawn=lambda *a: SimpleNamespace(pid=0, poll=lambda: None))
    assert r["auto_picked"][0]["picked"] == "s1"
    assert _j(root / "assets_v2/manifest.json")["characters"]["ch_zhuo_lin"]["looks"]["A"]["sheet"]["file"].endswith("_s1.png")


def test_worker_reload_keeps_asset_jobs_in_sync(monkeypatch):
    """常驻服务每拍重载 asset_worker：asset_jobs 也要跟着重载（02:17 新 worker + 旧 asset_jobs → AttributeError）"""
    monkeypatch.setattr(AJ, "AUTO_PICK_KINDS", None)                  # 模拟进程里还是旧的 asset_jobs
    AW2 = _load("asset_worker_reload_t", "tools/pipeline/asset_worker.py")
    assert AW2.AJ.AUTO_PICK_KINDS == ("face", "scene", "sheet", "item")


def _delegate(root, on: bool):
    _w(root / "config/pipeline/owner_delegate.json", {"schema": "nsfs.owner_delegate/1", "enabled": on, "enabled_at": "2026-11-03T02:00:00" if on else None,
                                                       "expiry": {"on_owner_decision": True, "expired_at": None}})


def test_derived_assets_go_to_queue_when_delegate_off(root, monkeypatch):
    """L-139：代选没开（或已到期）→ 设定图候选和单品裁图都投 #/queue 等项目方挑，不自动登记；开着才自动选用"""
    _delegate(root, False)
    assert AJ.delegate_active(root)[0] is False
    _delegate(root, True)
    assert AJ.delegate_active(root)[0] is True
    _delegate(root, False)
    _register_sheet(root, monkeypatch)                                   # 项目方手选的设定图（kind=sheet 走统一入口）
    jp = AJ.job_path(root, RUN, "item-ch_zhuo_lin-A-shoes1")
    j = AW.run_crop(jp, root, checker=lambda img, items: {"status": "pass", "ocr": {"status": "pass"}})
    assert j["state"] == "awaiting_pick" and j["candidates"][0]["key"] == "crop"
    assert "A_shoes1" not in (_j(root / "assets_v2/manifest.json")["characters"]["ch_zhuo_lin"]["looks"]["A"].get("items") or {})
    req = next(r for r in _j(root / "data/owner_queue/requests.json") if r["id"] == "pick:item:ch_zhuo_lin:A_shoes1")
    assert not req.get("auto_picked") and req["candidates"][0]["file"].endswith("_crop.png")
    OP.accept(root, req["id"], "crop", "", "fred")                       # 项目方确认 → 登记 + 部件映射
    assert OP.process(root, req["id"], "crop", "fred")["state"] == "done"
    assert _j(root / "assets_v2/manifest.json")["characters"]["ch_zhuo_lin"]["looks"]["A"]["items"]["A_shoes1"]["slot"] == "shoes"
    assert _j(root / "data/looks/item_map_overrides.json")[RUN]["ch_zhuo_lin"]["A"]["黑色细高跟"] == "A_shoes1"
    # 设定图候选：代选关着 → 普通 pick，不自动登记
    story, looks = AJ.p1(root, RUN)
    plan = AJ.plan_from_gap({"kind": "look", "who": "唐瑶", "what": "唐瑶 造型A 没有设定图"}, story, looks, 1)
    _w(root / "data/review_pages/x/tf.png", b"tang-face")
    AJ.register_pick(root, "face", {"id": "pick:face:ch_tang_yao", "run": RUN, "candidates": [{"key": "a", "file": "data/review_pages/x/tf.png", "contract_ok": True}]},
                     "a", "fred", push=False)
    sj = AJ._new_job(RUN, 1, plan, {"who": "唐瑶", "what": "x"})
    AJ.save_job(root, sj)
    out = AW.run_job(AJ.job_path(root, RUN, sj["id"]), "gpu36:0", root, renderer=fake_renderer(root), cfg={**AW.config(root), "candidates": {"sheet": 1}})
    assert out["state"] == "awaiting_pick"
    assert not (_j(root / "assets_v2/manifest.json")["characters"]["ch_tang_yao"].get("looks") or {}).get("A", {}).get("sheet")


# ------------------------------------------------------------------ W6 11-03：年龄判词解析 / 没收尾作业接管 / 超时 / golden 停生成
def test_age_verdict_parses_first_verdict_not_prefix():
    """根因：sheet-lead_f-O4 seed1100 看图答“画面里的人看起来是“成年”…”被旧解析判 fail。口径不放宽：未成年判词在前 = fail，没结论 = fail"""
    assert AC._age_status("画面里的人看起来是“成年”，因面部成熟度、体态和妆容均符合成年人特征。") == "pass"
    assert AC._age_status("成年，人物面部与身形比例符合成年女性特征，无未成年视觉元素。") == "pass"
    assert AC._age_status("像未成年，脸型稚嫩") == "fail"
    assert AC._age_status("看起来是未成年人") == "fail"
    assert AC._age_status("不确定") == "fail"
    assert AC._age_status("无人物") == "na"
    assert AC._age_status("") == "untested"
    # W6b（A6 P1-A）：首个判词是“成年”但否定 / 多人 / 不确定 → 失败关闭（完整反例表见 tests/test_asset_age_judge.py）
    for t in ("她是成年人；旁边的孩子未成年", "不像成年人，更像未成年", "不是成年人", "非成年", "大概率成年，但也可能是未成年", "成年女性，约 17 岁"):
        assert AC._age_status(t) == "fail", t
    p = AC.parse_bundle("1. 符合，单人\n年龄：画面里的人看起来是“成年”，体态成熟\n文字：无\n总结：全部符合", 1)
    assert p["age"]["status"] == "pass" and p["ocr"]["status"] == "pass"


def _sheet_job_with_cands(root, monkeypatch, state="running", n_pass=2):
    story, looks = AJ.p1(root, RUN)
    _w(root / "data/review_pages/x/tf.png", b"tang-face")
    AJ.register_pick(root, "face", {"id": "pick:face:ch_tang_yao", "run": RUN, "candidates": [{"key": "a", "file": "data/review_pages/x/tf.png", "contract_ok": True}]},
                     "a", "fred", push=False)
    plan = AJ.plan_from_gap({"kind": "look", "who": "唐瑶", "what": "唐瑶 造型A 没有设定图"}, story, looks, 1)
    j = AJ._new_job(RUN, 1, plan, {"who": "唐瑶", "what": "x"})
    rd = AW.review_dir(root, j)
    rd.mkdir(parents=True, exist_ok=True)
    j["candidates"] = [{"seed": 1100, "passed": False, "label": {"age": "fail"}, "file": "data/ab/x.png", "thumb": None, "sha256": None}]
    for seed in range(1101, 1101 + n_pass):
        f = rd / f"{j['id']}_s{seed}.png"
        f.write_bytes(f"png-{seed}".encode())
        _w(rd / f"{j['id']}_s{seed}.json", {"seed": seed, "passed": True, "vlm": {"items": [{"ok": True}]}})
        j["candidates"].append({"seed": seed, "passed": True, "label": {"age": "pass"}, "file": str(f.relative_to(root)).replace("\\", "/"),
                                "thumb": None, "sha256": _sha(f.read_bytes())})
    j.update(state=state, attempts=1, pid=999999, lane="gpu33:0" if state == "running" else None, started_at=AJ._now())
    AJ.save_job(root, j)
    monkeypatch.setattr(AW, "_pid_alive", lambda pid: False)
    return j


def test_dead_child_with_passed_candidates_is_salvaged_not_rerendered(root, monkeypatch):
    _delegate(root, False)
    j = _sheet_job_with_cands(root, monkeypatch)
    spawned = []
    ln = FakeLanes()
    r = AW.tick(root, cfg=AW.config(root), runs={RUN: 1}, spawn=lambda *a: spawned.append(a), lanes=lambda c, u: ["gpu36:0"], check=lambda run, ep: {"ready": False, "gaps": []}, ln=ln)
    j2 = AJ.load_job(AJ.job_path(root, RUN, j["id"]))
    assert j2["state"] == "awaiting_pick" and j2["pid"] is None and not spawned
    assert r["salvaged"][0]["id"] == j["id"] and r["salvaged"][0]["candidates"] == 2
    assert ("gpu33:0", AW.BY, "hold") in ln.released
    req = next(x for x in _j(root / "data/owner_queue/requests.json") if x["id"] == j["pick_id"])
    assert [c["key"] for c in req["candidates"]] == ["s1101", "s1102"] and all(c["contract_ok"] for c in req["candidates"])
    assert any("接管收尾" in x for x in j2["log"])


def test_pending_job_left_with_passed_candidates_is_salvaged(root, monkeypatch):
    _delegate(root, False)
    j = _sheet_job_with_cands(root, monkeypatch, state="pending")
    spawned = []
    gap = {"kind": "look", "who": "唐瑶", "what": "唐瑶 造型A 没有设定图", "owner": "资产线", "shots": [1]}     # 缺口还在（否则 close_stale 会收掉）
    AW.tick(root, cfg=AW.config(root), runs={RUN: 1}, spawn=lambda *a: spawned.append(a), lanes=lambda c, u: ["gpu36:0"], check=lambda run, ep: {"ready": False, "gaps": [gap]}, ln=FakeLanes())
    assert AJ.load_job(AJ.job_path(root, RUN, j["id"]))["state"] == "awaiting_pick" and not spawned


def test_salvage_refuses_tampered_or_too_few_candidates(root, monkeypatch):
    j = _sheet_job_with_cands(root, monkeypatch, n_pass=1)
    assert AW.salvage_records(root, j) and not AW.try_salvage(root, j, AW.config(root), {}, "x")
    j["candidates"][1]["sha256"] = "0" * 64
    assert AW.salvage_records(root, j) == []


def test_dead_child_without_enough_candidates_fails_then_reports(root, monkeypatch):
    j = _sheet_job_with_cands(root, monkeypatch, n_pass=1)
    j["attempts"] = 2
    AJ.save_job(root, j)
    # W-FIX-PIPE #13：定案失败默认先自动换种子重排（auto_requeue_max）；这里关掉它，验原来的“定案 + 报卡点”
    AW.tick(root, cfg={**AW.config(root), "auto_requeue_max": 0}, runs={RUN: 1}, spawn=lambda *a: None, lanes=lambda c, u: [],
            check=lambda run, ep: {"ready": False, "gaps": []}, ln=FakeLanes())
    j2 = AJ.load_job(AJ.job_path(root, RUN, j["id"]))
    assert j2["state"] == "failed" and j2["final"] is True and "没收尾" in j2["error"]
    assert "连续失败" in (root / "data/pipeline/issues.jsonl").read_text(encoding="utf-8")


def _timeout_job(root, monkeypatch, proc=None):
    j = _sheet_job_with_cands(root, monkeypatch, n_pass=0)
    j["started_at"] = "2026-01-01T00:00:00"
    if proc is not None:
        j["proc"] = proc
    AJ.save_job(root, j)
    killed = []
    monkeypatch.setattr(AW, "_kill", lambda pid: killed.append(pid))
    return j, killed


def _tick_once(root):
    return AW.tick(root, cfg={**AW.config(root), "render": False}, runs={RUN: 1}, spawn=lambda *a: None, lanes=lambda c, u: [],
                   check=lambda run, ep: {"ready": False, "gaps": []}, ln=FakeLanes())


PROC = {"pid": 999999, "sig": 1234567, "cmd_sha1": hashlib.sha1(b"CMD").hexdigest()}


def test_running_job_past_timeout_is_killed_when_identity_matches(root, monkeypatch):
    j, killed = _timeout_job(root, monkeypatch, dict(PROC))
    monkeypatch.setattr(AW, "proc_sig", lambda pid: 1234567 if pid == 999999 else None)
    monkeypatch.setattr(AW, "proc_cmdline", lambda pid: "CMD")
    r = _tick_once(root)
    j2 = AJ.load_job(AJ.job_path(root, RUN, j["id"]))
    assert killed == [999999] and j2["state"] == "pending" and "超时" in j2["error"] and "核过身份" in j2["error"] and j2["pid"] is None
    assert r["timeouts"] == [{"id": j["id"], "pid": 999999, "killed": True, "why": "timeout"}]


@pytest.mark.parametrize("live_sig,cmdline,legacy", [
    (7654321, "CMD", False),         # 同一 pid 换了进程（创建时间不同）：判活就判死，不杀
    (1234567, "其他进程的命令行", False),   # 创建时间巧合一致但命令行不同：不杀
    (1234567, None, False),          # 命令行读不到：核不了 = 不杀
    (None, None, True),              # 旧作业没记 proc，只有 pid（W6 旧数据）：超时也不杀
])
def test_timeout_never_kills_unverified_pid(root, monkeypatch, live_sig, cmdline, legacy):
    j, killed = _timeout_job(root, monkeypatch, None if legacy else dict(PROC))
    monkeypatch.setattr(AW, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(AW, "proc_sig", lambda pid: live_sig)
    monkeypatch.setattr(AW, "proc_cmdline", lambda pid: cmdline)
    _tick_once(root)
    j2 = AJ.load_job(AJ.job_path(root, RUN, j["id"]))
    assert killed == []
    assert j2["error"].startswith("pid_mismatch") and j2["pid"] is None
    if live_sig == 7654321:
        assert j2["state"] == "pending"                            # 原子进程已退出：普通“没收尾”，按 attempts 重排
    else:
        assert j2["state"] == "failed" and j2["final"] is True       # 可能还在跑：定案 + 登记卡点，不重起抢道
        assert "连续失败" in (root / "data/pipeline/issues.jsonl").read_text(encoding="utf-8")


def test_start_records_proc_identity_in_job_file(root, monkeypatch):
    j = _sheet_job_with_cands(root, monkeypatch, n_pass=0, state="pending")
    monkeypatch.setattr(AW, "proc_sig", lambda pid: 42 if pid == 4321 else None)
    fake = SimpleNamespace(pid=4321, args=["python.exe", "-X", "utf8", "asset_worker.py", "run-job", "--job", "C:/a b/x.json"])
    AW._start(root, j, "gpu36:0", lambda *a: fake, {"started": []})
    j2 = AJ.load_job(AJ.job_path(root, RUN, j["id"]))
    want = hashlib.sha1(subprocess.list2cmdline(fake.args).encode("utf-8")).hexdigest()
    assert j2["pid"] == 4321 and j2["proc"] == {"pid": 4321, "sig": 42, "cmd_sha1": want}


def test_proc_sig_reuses_agent_dispatcher():
    src = (ROOT / "tools/pipeline/asset_worker.py").read_text(encoding="utf-8")
    assert "_disp().proc_sig" in src and "GetProcessTimes" not in src           # 创建时间只有 agent_dispatcher 一份实现
    assert AW._disp().proc_sig.__code__.co_filename.replace("\\", "/").endswith("tools/factory/agent_dispatcher.py")


def test_verify_proc_on_a_real_child_process():
    """真起一个短命子进程：记身份 → 核得上；pid / 创建时间 / 命令行任一改掉 → 核不上（含 Windows 命令行 = list2cmdline 的假设）"""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        ident = AW.proc_identity(p)
        assert ident["sig"] is not None and ident["cmd_sha1"]
        ok, why = AW.verify_proc(p.pid, ident)
        assert ok, why
        assert not AW.verify_proc(p.pid, {**ident, "sig": ident["sig"] + 1})[0]
        assert not AW.verify_proc(p.pid, {**ident, "cmd_sha1": "0" * 40})[0]
        assert not AW.verify_proc(p.pid + 4, ident)[0]
        assert not AW.verify_proc(p.pid, {"pid": p.pid})[0]
    finally:
        p.kill()
        p.wait()
    assert AW.proc_sig(p.pid) is None or AW.proc_sig(p.pid) != ident["sig"]


def test_ensure_golden_only_records_and_keeps_legacy_job(root):
    legacy = AJ.job_path(root, RUN, "golden-ep01")
    _w(legacy, {"id": "golden-ep01", "kind": "golden", "state": "pending"})
    before = legacy.read_bytes()
    g = AJ.ensure_golden(root, RUN, 1, {"shots": [{"index": 1, "adult": False}]})
    assert g["ready_for"] == "producer" and g["legacy_job"] == "golden-ep01" and legacy.read_bytes() == before
    assert AJ.ensure_golden(root, RUN, 2, {"shots": []})["legacy_job"] is None
    assert not AJ.job_path(root, RUN, "golden-ep02").is_file()
    src = (ROOT / "tools/pipeline/asset_jobs.py").read_text(encoding="utf-8")
    assert "golden_v2.py --render" not in src


# ------------------------------------------------------------------ W6c+（A9 第 25 轮 P1-①）：设定图派生单品不重画项目方已上传的同一件
OWNER_ZH = "服装=日常全身装：黑色漆皮抹胸紧身短裙 + 黑色薄透丝袜（全身参考照）配黑色短靴｜鞋=SH1 或 SH2｜饰品=0件、金色细链手包"


def _owner_look(root, with_owner_item=True):
    looks = _j(root / f"data/pipeline/runs/{RUN}/P1_looks.json")
    for c in looks:
        if c["char_id"] == "ch_zhuo_lin":
            c["looks"][0]["zh"] = OWNER_ZH
    _w(root / f"data/pipeline/runs/{RUN}/P1_looks.json", looks)
    if with_owner_item:
        man = _j(root / "assets_v2/manifest.json")
        man["characters"]["ch_zhuo_lin"] = {"display_name": "卓琳", "looks": {"A": {"items": {"A_garment": {
            "file": "assets_v2/characters/ch_zhuo_lin/outfits/garment.png", "sha256": "0" * 64,
            "name": "日常全身装：黑色漆皮抹胸紧身短裙 + 黑色薄透丝袜（全身参考照）", "source": "项目方上传 assets_v2/inbox/O15_worn_s0.png"}}}}}
        _w(root / "assets_v2/manifest.json", man)


@pytest.mark.parametrize("with_owner_item", [True, False])
def test_plan_items_skips_owner_uploaded_ref_photo_and_zero_count(root, with_owner_item):
    _owner_look(root, with_owner_item)
    sk = []
    made = AJ.plan_items_from_sheet(root, RUN, "ch_zhuo_lin", "A", 1, {"file": "x/sheet.png", "sha256": "1" * 64}, skipped=sk)
    whys = {x["part"]: x["why"] for x in sk}
    garment = "日常全身装：黑色漆皮抹胸紧身短裙 + 黑色薄透丝袜（全身参考照）"
    assert garment in whys and "C-23" in whys[garment]
    assert ("A_garment" in whys[garment]) is with_owner_item            # 清单有 → 引用它；没有 →“参考照”也不自己画
    assert "SH1 或 SH2" in whys and "0件" in whys                        # 项目方编号 / “0件”明确跳过并记理由
    assert made == ["item-ch_zhuo_lin-A-outfit1", "item-ch_zhuo_lin-A-acc1"]   # 正常单品照常生成（服装编号不被跳过项占用）
    assert not AJ.job_path(root, RUN, "item-ch_zhuo_lin-A-outfit2").exists()
    assert AJ.load_job(AJ.job_path(root, RUN, "item-ch_zhuo_lin-A-outfit1"))["spec"]["label"] == "黑色短靴"


def test_plan_items_dry_writes_nothing(root):
    _owner_look(root)
    before = sorted(p.name for p in AJ.jobs_dir(root, RUN).glob("*")) if AJ.jobs_dir(root, RUN).exists() else []
    made = AJ.plan_items_from_sheet(root, RUN, "ch_zhuo_lin", "A", 1, {"file": "x", "sha256": "1" * 64}, skipped=[], dry=True)
    assert made and not any(AJ.job_path(root, RUN, m).exists() for m in made)
    assert (sorted(p.name for p in AJ.jobs_dir(root, RUN).glob("*")) if AJ.jobs_dir(root, RUN).exists() else []) == before


def test_no_item_zero_count_and_owner_item_matching():
    for s in ("0件", "0 件", "0件。", "无", "无。"):
        assert AJ.no_item(s), s
    assert AJ.no_item("金色细链手包") is None
    P = SimpleNamespace
    char = {"items": {"SH1": {"slot": "shoes", "name": "透明尖头细高跟", "file": "f", "source": "assets_v2/…/outfit.png"}}}   # 派生裁图不算项目方上传
    assert AJ.owner_item_for(char, "A", P(slot="shoes", label="透明尖头细高跟")) is None
    char["items"]["SH1"]["source"] = "项目方上传 assets_v2/inbox/x.png"
    assert AJ.owner_item_for(char, "A", P(slot="shoes", label="透明尖头细高跟"))[0] == "SH1"


def test_after_pick_logs_skipped_parts(root, monkeypatch):
    _owner_look(root)
    _register_sheet(root, monkeypatch)
    sj = next(j for j in AJ.list_jobs(root, RUN) if j["kind"] == "sheet")
    assert any("不生成作业" in x and "0件" in x for x in sj["log"]) and any("A_garment" in x for x in sj["log"])


# ------------------------------------------------------------------ W6c+（A9 P1-②）：scene 也不带镜头语言 / 融合句；face / sheet 不变
def _fake_fj(monkeypatch, prompt):
    seen = {}

    class FakeFJ:
        @staticmethod
        def build_first(run, ep, shot, g, mode="shot", prompt_override=None):
            seen["mode"], seen["override"] = mode, prompt_override
            return {"prompt": prompt_override or prompt, "refs": []}

        @staticmethod
        def trace_of(jc):
            return {}

    import ns_agent
    monkeypatch.setitem(sys.modules, "ns_agent.frame_job", FakeFJ)
    monkeypatch.setattr(ns_agent, "frame_job", FakeFJ, raising=False)
    monkeypatch.setenv("NS_RUN", "demo")
    monkeypatch.setattr(AW, "script_for", lambda job: SimpleNamespace(episodes=[SimpleNamespace(shots=[None])], globals=None))
    monkeypatch.setattr(AW, "empty_suffix", lambda jc, spec: jc)
    monkeypatch.setattr(AW, "require_face_ref", lambda root, job, jc: None)
    return seen


@pytest.mark.parametrize("kind,mode", [("face", "sheet"), ("sheet", "sheet"), ("item", "sheet"), ("scene", "sheet")])
def test_compile_mode_per_kind(monkeypatch, kind, mode):
    """W-ASSETS 11-06：face 也走 sheet 模式（prompt_override = spec.img + 年龄锚点），其余不变"""
    seen = _fake_fj(monkeypatch, "空镜，无人物，影棚白幕")
    spec = {"img": AJ.PORTRAIT + "成年女性卓琳，35岁，薄唇" + AJ.NEUTRAL, "age": 35} if kind == "face" else {}
    AW._compile({"kind": kind, "run": "demo", "spec": spec})
    assert seen["mode"] == mode
    assert (seen.get("override") or "").startswith(AJ.PORTRAIT) if kind == "face" else seen.get("override") is None


def test_scene_compile_guard_blocks_person_paragraph(monkeypatch):
    _fake_fj(monkeypatch, "空镜，镜头：35mm，人物和环境一起清楚。人物和场景是同一次拍摄：环境光染到皮肤和衣服上")
    with pytest.raises(RuntimeError, match="空镜底图"):
        AW._compile({"kind": "scene", "run": "demo", "spec": {}})
    AW._compile({"kind": "sheet", "run": "demo", "spec": {}})       # sheet / face 不加这道守卫（人像本来就有人）
    AW._compile({"kind": "face", "run": "demo", "spec": {"img": AJ.PORTRAIT + "成年女性卓琳，35岁，薄唇" + AJ.NEUTRAL, "age": 35}})


REAL_JOBS = {"face": "face-ch_zhuo_lin", "sheet": "sheet-lead_f-O4", "item": "item-ch_zhuo_lin-A-acc1", "scene": "scene-sk_white_cyc"}


@pytest.mark.parametrize("kind", list(REAL_JOBS))
def test_real_compile_four_kinds(monkeypatch, kind):
    """真编译（真实作业文件只读，不出图）：item / scene 无镜头语言段、无人像融合句；sheet 无镜头语言段；
    face（W-ASSETS 11-06）= sheet 模式 + prompt_override：spec.img 原文 + 年龄锚点，无镜头语言段 / 融合句 / 视线句"""
    jp = AJ.job_path(AJ.ROOT, "series10_v2", REAL_JOBS[kind])
    if not jp.is_file():
        pytest.skip(f"没有真实作业 {jp.name}")
    monkeypatch.setenv("NS_RUN", "series10_v2")
    j = AJ.load_job(jp)
    if kind == "scene" and not j["spec"].get("suffix"):        # 旧格式 scene 作业没有 spec.suffix：内存里补（与新生成的作业同口径）
        j["spec"]["suffix"] = AJ.scene_suffix(j["spec"].get("time") or "", j["spec"].get("light") or "")
        j["spec"].setdefault("negative", AJ.EMPTY_NEGATIVE)
    p = AW._compile(j, AJ.ROOT)["prompt"]
    if kind == "face":
        # 身份脸 = spec.img 原文（P1 年龄 / 长相 / 中性纯色背景）+ 年龄锚点 + 本剧风格后缀；不再有剧情镜的镜头段 / 融合句 / “以参考图为准”
        sp = j["spec"]
        assert AJ.PORTRAIT in p and f"{sp['age']}岁，看起来就是{sp['age']}岁" in p and AJ.NEUTRAL.strip("，") in p   # 真实清单里卓琳已有脸 → 前面可能带参考槽标注
        assert "以参考图为准" not in p and "极浅景深" not in p and "人物和场景是同一次拍摄" not in p and "人物和环境一起清楚" not in p
    else:
        assert "镜头：" not in p and not any(x in p for x in ("人物和场景是同一次拍摄", "人物和环境一起清楚", "环境光染到皮肤", "四分之三侧脸"))
    if kind in ("item", "scene"):
        assert AW.person_phrases(p) == []


# ------------------------------------------------------------------ W6c+（A6b 第 23 轮 P2）：身份核不上定案后——不先 salvage、道不提前放、子进程不覆盖状态
def _unverified_job(root, monkeypatch, alive):
    j2 = _sheet_job_with_cands(root, monkeypatch, n_pass=2)       # 带 2 张过检候选（够 salvage）
    j2.update(started_at="2026-01-01T00:00:00", proc=dict(PROC))
    AJ.save_job(root, j2)
    killed = []
    monkeypatch.setattr(AW, "_kill", lambda pid: killed.append(pid))
    monkeypatch.setattr(AW, "_PROCS", {})                        # 别的用例 _start 留下的替身进程不串进来（生产每拍重载也是空的）
    monkeypatch.setattr(AW, "proc_sig", lambda pid: 1234567 if alive["v"] else None)
    monkeypatch.setattr(AW, "proc_cmdline", lambda pid: "其他进程的命令行")
    return j2, killed


def test_unverified_timeout_holds_lane_and_salvages_only_after_exit(root, monkeypatch):
    _delegate(root, False)
    alive = {"v": True}
    j, killed = _unverified_job(root, monkeypatch, alive)
    ln = FakeLanes()
    tk = lambda: AW.tick(root, cfg={**AW.config(root), "render": False}, runs={RUN: 1}, spawn=lambda *a: None, lanes=lambda c, u: [],
                         check=lambda run, ep: {"ready": False, "gaps": []}, ln=ln)
    r = tk()
    s = AJ.load_job(AJ.job_path(root, RUN, j["id"]))
    assert killed == [] and s["state"] == "failed" and s["final"] is True and s["error"].startswith("pid_mismatch")
    assert s["lane_suspect"] == "gpu33:0" and not ln.released                 # 道不放
    assert not r.get("salvaged")                                               # 不先 salvage
    assert ("gpu33:0", AW.BY) in ln.held                                      # 续 hold
    tk()                                                                       # 还活着：照旧挡着
    assert not ln.released and AJ.load_job(AJ.job_path(root, RUN, j["id"]))["state"] == "failed"
    alive["v"] = False                                                         # 核验到退出
    r = tk()
    s = AJ.load_job(AJ.job_path(root, RUN, j["id"]))
    assert ("gpu33:0", AW.BY, "hold") in ln.released and "lane_suspect" not in s and s["lane"] is None
    assert r["salvaged"][0]["id"] == j["id"] and s["state"] == "awaiting_pick"  # 先核验、后接管


def test_child_cannot_overwrite_settled_state(root, monkeypatch):
    """tick 已定案（failed + final）后子进程 run_job 收尾：状态只增不改——候选 / 日志并进去，state / error / final 保持；不投待办"""
    _delegate(root, False)
    j = _sheet_job_with_cands(root, monkeypatch, n_pass=0)
    jp = AJ.job_path(root, RUN, j["id"])
    calls = []

    def renderer(job, lane, seed, _root):
        if not calls:                               # 出第一张时 tick 那边定案了
            d = AJ.load_job(jp)
            d.update(state="failed", final=True, error="pid_mismatch：测试", lane_suspect="gpu33:0")
            AJ.save_job(root, d)
        calls.append(seed)
        return fake_renderer(root)(job, lane, seed, _root)

    out = AW.run_job(jp, "gpu33:0", root, renderer=renderer, cfg=AW.config(root))
    s = AJ.load_job(jp)
    assert s["state"] == "failed" and s["final"] is True and s["error"] == "pid_mismatch：测试" and s["lane_suspect"] == "gpu33:0"
    assert len(calls) == 1 and any(c.get("seed") == calls[0] and c.get("passed") for c in s["candidates"])   # 定案后不再出新种子
    assert any("不投待办" in x for x in s["log"]) and out["state"] == "failed"
    reqs = _j(root / "data/owner_queue/requests.json") if (root / "data/owner_queue/requests.json").exists() else []
    assert not any(x.get("id") == j["pick_id"] for x in reqs)


def test_requeued_suspect_job_not_restarted_while_child_alive(root, monkeypatch):
    """W6c：身份核不上定案后被人工 requeue 成 pending，可疑子进程还活着 → 不起新子进程、不 salvage；确认退出后才放道、正常接手"""
    _delegate(root, False)
    alive = {"v": True}
    j, killed = _unverified_job(root, monkeypatch, alive)
    ln = FakeLanes()
    started = []
    tk = lambda: AW.tick(root, cfg={**AW.config(root), "render": True}, runs={RUN: 1}, spawn=lambda *a: started.append(a),
                         lanes=lambda c, u: ["gpu36:0"], check=lambda run, ep: {"ready": False, "gaps": []}, ln=ln)
    tk()
    AJ.requeue(root, RUN, j["id"], "测试：人工重排")
    (AJ.jobs_dir(root, RUN) / "_recheck").unlink(missing_ok=True)   # 本用例 check 不报缺口：别让重生成把作业当“缺口已不在”收掉
    s = AJ.load_job(AJ.job_path(root, RUN, j["id"]))
    assert s["state"] == "pending" and s["lane_suspect"] == "gpu33:0"
    r = tk()
    s = AJ.load_job(AJ.job_path(root, RUN, j["id"]))
    assert started == [] and not r.get("salvaged") and j["id"] in r.get("suspect_waiting", [])
    assert s["state"] == "pending" and s["lane_suspect"] == "gpu33:0" and not ln.released and killed == []
    alive["v"] = False
    r = tk()
    s = AJ.load_job(AJ.job_path(root, RUN, j["id"]))
    assert ("gpu33:0", AW.BY, "hold") in ln.released and "lane_suspect" not in s
    assert r["salvaged"][0]["id"] == j["id"] and s["state"] == "awaiting_pick" and started == []


# ------------------------------------------------------------------ W6c 追加（总调度 11-03）：count=untested = 没测出，不能判不过
def _untested_render(root, count="untested", vlm_error=None, extra=None):
    """出图替身：候选落盘，但人数检查（anomaly）没跑成 → count=untested（隧道断 / 服务不在）"""
    def render(job, lane, seed, _r):
        rd = AW.review_dir(root, job)
        rd.mkdir(parents=True, exist_ok=True)
        f = rd / f"{job['id']}_s{seed}.png"
        f.write_bytes(f"png-{job['id']}-{seed}".encode())
        rel = str(f.relative_to(root)).replace("\\", "/")
        lab = {"identity": "na", "count": count, "q9": "pass", "prompt_vlm": "pass", "ocr": "pass", "age": "pass", **(extra or {})}
        return {"seed": seed, "passed": False, "label": lab, "file": rel, "anomaly": {"status": "error", "note": "连不上 gpu36"},
                "vlm": {"error": vlm_error, "items": []}, "postflight": {"items": []}}
    return render


def test_unmeasured_keys_only_for_infra_gaps():
    assert AC.unmeasured_keys({"count": "untested", "q9": "pass", "age": "pass"}) == ["count"]
    assert AC.unmeasured_keys({"count": "untested", "age": "fail"}) == []                       # 有一项明确 fail = 真不过
    assert AC.unmeasured_keys({"count": "pass", "prompt_vlm": "untested"}) == []                 # 看图答漏项但服务没报错：不算没测出
    assert AC.unmeasured_keys({"count": "pass", "prompt_vlm": "untested", "age": "untested"}, {"error": "timeout"}) == ["prompt_vlm", "age"]
    assert AC.unmeasured_keys({"count": "pass", "age": "pass"}) == []


def test_count_untested_does_not_fail_job_and_backs_off(root):
    """15:14–15:24 face-ch_li_an 复现：每张 count=untested → 作业不 failed、不计 attempts、退避 5 分钟、候选标 unmeasured"""
    AJ.generate(RUN, 1, root, check=fake_check(root))
    jp = AJ.job_path(root, RUN, "face-ch_zhuo_lin")
    j0 = AJ.load_job(jp)
    j0.update(state="running", attempts=1)
    AJ.save_job(root, j0)
    cfg = {**AW.config(root), "candidates": {"face": 2}}
    j = AW.run_job(jp, "gpu36:0", root, renderer=_untested_render(root), cfg=cfg)
    assert j["state"] == "pending" and j["attempts"] == 0 and not j.get("final")
    assert "看图服务不可用，等待重试" in j["error"] and "不过" not in j["error"]
    assert AW._backing_off(j) and not AW._backing_off(j, now=time.time() + 301)
    assert len(j["candidates"]) == 2 and all(c["unmeasured"] == ["count"] and not c["passed"] for c in j["candidates"])   # 连续 2 张没测出就停，不烧 4 粒种子
    assert not (root / "data/pipeline/issues.jsonl").exists() or "连续失败" not in (root / "data/pipeline/issues.jsonl").read_text(encoding="utf-8")
    # 混合：1 张真不过 + 没测出 → 仍退避重试，不 failed
    j1 = AJ.load_job(jp)
    j1.update(state="running", attempts=1, candidates=[])
    AJ.save_job(root, j1)
    seq = iter([_untested_render(root, count="fail"), _untested_render(root), _untested_render(root), _untested_render(root)])
    j1 = AW.run_job(jp, "gpu36:0", root, renderer=lambda *a: next(seq)(*a), cfg=cfg)
    assert j1["state"] == "pending" and j1["attempts"] == 0 and "1 张不过" in j1["error"] and "没测出" in j1["error"]
    # 全部真不过（count=fail）照旧 failed
    j2 = AJ.load_job(jp)
    j2.update(state="running", attempts=1, candidates=[])
    AJ.save_job(root, j2)
    j2 = AW.run_job(jp, "gpu36:0", root, renderer=_untested_render(root, count="fail"), cfg=cfg)
    assert j2["state"] == "failed" and "人数 不过" in j2["error"]


def test_unmeasured_job_waits_backoff_then_retries_in_tick(root):
    """tick：没测出的作业退避期内不起子进程（不占道）；退避过了再起，服务恢复后正常过检投待办，attempts 不被没测出那轮吃掉"""
    cfg = AW.config(root)
    check = fake_check(root)
    ln = FakeLanes()
    state = {"down": True}

    def spawn(job, jp, lane):
        if job["kind"] == "voice":
            return SimpleNamespace(pid=0, poll=lambda: 0)
        AW.run_job(jp, lane, root, renderer=_untested_render(root) if state["down"] else fake_renderer(root), cfg=cfg)
        return SimpleNamespace(pid=0, poll=lambda: 0)
    lanes = lambda c, in_use: ["gpu36:0", "gpu36:1"]   # noqa: E731
    for _ in range(4):                                                                 # 头一拍只生成作业；道按顺序派
        AW.tick(root, cfg=cfg, spawn=spawn, lanes=lanes, check=check, ln=ln)
        j = AJ.load_job(AJ.job_path(root, RUN, "face-ch_zhuo_lin"))
        if j.get("retry_after"):
            break
    assert j["state"] == "pending" and j["attempts"] == 0 and j.get("retry_after"), j["log"]
    starts = sum(1 for l in j["log"] if "起子进程" in l)
    rec = AW.tick(root, cfg=cfg, spawn=spawn, lanes=lanes, check=check, ln=ln)      # 退避期内：不起
    j = AJ.load_job(AJ.job_path(root, RUN, "face-ch_zhuo_lin"))
    assert sum(1 for l in j["log"] if "起子进程" in l) == starts and j["state"] == "pending"
    assert any(x["id"] == "face-ch_zhuo_lin" for x in rec.get("unmeasured_backoff") or [])
    for jj in AJ.list_jobs(root, RUN):                                                 # 退避到期 + 服务恢复
        if jj.get("retry_after"):
            jj["retry_after"] = "2000-01-01T00:00:00"
            AJ.save_job(root, jj)
    state["down"] = False
    for _ in range(4):
        AW.tick(root, cfg=cfg, spawn=spawn, lanes=lanes, check=check, ln=ln)
        j = AJ.load_job(AJ.job_path(root, RUN, "face-ch_zhuo_lin"))
        if j["state"] != "pending":
            break
    assert j["state"] == "awaiting_pick" and j["attempts"] == 1 and not j.get("retry_after")


def test_comfy_unavailable_backs_off_not_failed_scene_w31(root):
    """ISS-1103-155905-9a0f 复现：出图机连不上（ComfyUnavailable）+ 看图排队超时 → 退避重排、不计 attempts、不 failed、不登记卡点；
    真不过（内容）才 failed，并且卡点写“要项目方挑场景底图”"""
    class ComfyUnavailable(RuntimeError):
        pass
    AJ.generate(RUN, 1, root, check=fake_check(root))
    sc = next(j for j in AJ.list_jobs(root, RUN) if j["kind"] == "scene")
    jp = AJ.job_path(root, RUN, sc["id"])
    j0 = AJ.load_job(jp)
    j0.update(state="running", attempts=2)
    AJ.save_job(root, j0)
    cfg = {**AW.config(root), "candidates": {"scene": 2}}
    seq = iter([AW.Q9Timeout("排队超时"), ComfyUnavailable("/prompt: [WinError 10061] refused"), ComfyUnavailable("x"), ComfyUnavailable("y")])

    def boom(*a):
        raise next(seq)
    j = AW.run_job(jp, "gpu33:0", root, renderer=boom, cfg=cfg)
    assert j["state"] == "pending" and j["attempts"] == 1 and AW._backing_off(j) and not j.get("final"), j["log"]
    issues = root / "data/pipeline/issues.jsonl"
    assert not issues.exists() or "连续失败" not in issues.read_text(encoding="utf-8")
    # 真不过 → failed；_fail 终局的卡点 hint 指向项目方挑场景底图
    j1 = AJ.load_job(jp)
    j1.update(state="running", attempts=2, candidates=[], retry_after=None)
    AJ.save_job(root, j1)
    j1 = AW.run_job(jp, "gpu33:0", root, renderer=_untested_render(root, count="fail"), cfg=cfg)
    assert j1["state"] == "failed"
    AW._fail(root, j1, cfg, j1["error"], {"failed": []}, final=True)
    assert "项目方挑场景底图" in issues.read_text(encoding="utf-8")


# ------------------------------------------------------------------ W-ASSETS 11-06：身份脸作业（ep02 黎岸 / 周序 被挡两天的三个根因）
def test_face_prompt_anchors_age_and_keeps_p1_text():
    """身份脸提示词 = spec.img（P1 原文不改）+ 按 spec.age 的编译期年龄锚点（正向写法）；否定项进负面词。
    根因：提示词模板 v2 的 shot 模式把人物描述换成“以参考图为准”，身份脸没有参考图 → 25 岁周序 16/16 出成 40 岁"""
    base = AJ.PORTRAIT + "成年男性周序，25岁，结实中等身高，黑色寸头，表情平静自然，真实皮肤质感与成熟的五官轮廓" + AJ.NEUTRAL
    p = AW.face_prompt({"cid": "ch_zhou_xu", "img": base, "age": 25})
    assert p.startswith(AJ.PORTRAIT) and "25岁，看起来就是25岁的年轻人：皮肤紧致光滑" in p and "发际线饱满" in p
    assert "结实中等身高，黑色寸头" in p and p.endswith(AJ.NEUTRAL)                     # P1 段落原样保留、背景句仍在末尾
    assert "成熟的五官轮廓" not in p and "清晰的五官轮廓" in p                        # 外壳句对青年是反向锚点
    assert "发际线后移" in AW.face_negative({"age": 25}) and "中年人外观" in AW.face_negative({"age": 25})
    p38 = AW.face_prompt({"cid": "ch_li_an", "img": base.replace("周序，25岁", "黎岸，38岁"), "age": 38})
    assert "38岁，看起来就是38岁的成熟成年人" in p38 and "成熟的五官轮廓" in p38 and "发际线后移" not in AW.face_negative({"age": 38})
    with pytest.raises(RuntimeError, match="spec.img / spec.age"):
        AW.face_prompt({"cid": "x", "img": "", "age": 25})


def test_face_count_refless_and_vlm_fallback():
    """人数检查：身份脸作业的人就是还没有身份脸的那个人 → cast 行 refless=True 只数头（原来 judge 因“身份参照没加载”张张 untested，
    作业永远退避）；检测器真没跑成（隧道 / rssh 断）→ 用合并看图第 1 条兜底，看图也没答才仍 untested"""
    sys.path.insert(0, str(ROOT / "tools/vqa"))
    import anomaly as A
    feat = {"H": 1000, "W": 800, "faces": [{"box": [300, 200, 500, 450], "score": 0.9, "emb": [1.0, 0.0], "sims": {}}], "refs_loaded": [], "persons": [], "dw": [], "hands": []}
    cast = [{"name": "周序", "presence": "在画", "faced": True, "x": "中", "refless": True}]
    r = A.judge(feat, cast)
    assert r["verdict"] == "clean" and not r["untested"]
    two = {**feat, "faces": feat["faces"] + [{"box": [50, 200, 250, 450], "score": 0.9, "emb": [0.0, 1.0], "sims": {}}]}
    assert [d["code"] for d in A.judge(two, cast)["defects"]] == ["extra_head"]
    an = {"status": "untested", "reasons": ["常驻检测服务不可用"], "mode": "error"}
    assert AW.count_fallback(an, {"items": [{"n": 1, "ok": True, "text": "符合"}]})["status"] == "pass"
    assert AW.count_fallback(an, {"items": [{"n": 1, "ok": False, "text": "不符合，两个人"}]})["status"] == "fail"
    assert AW.count_fallback(an, {"error": "看图挂了", "items": [{"n": 1, "ok": True}]})["status"] == "untested"
    assert AW.count_fallback(an, {"items": [{"n": 1, "ok": True, "untested": True}]})["status"] == "untested"
    assert AW.count_fallback({"status": "fail", "reasons": ["extra_head"]}, {"items": [{"n": 1, "ok": True}]})["status"] == "fail"


def test_face_auto_pick_when_delegate_on_l198(root, monkeypatch):
    """L-198：代选开着 → 身份脸候选过检后系统按分数自动登记（manifest characters[cid].face，picked_by 系统自动），
    inbox 一条“已自动选用，可修改”的告知；代选关着（test_full_round…）照旧投 #/queue"""
    _delegate(root, True)
    monkeypatch.setattr(AJ, "_checker", lambda: fake_check(root))
    story, looks = AJ.p1(root, RUN)
    plan = AJ.plan_from_gap({"kind": "face", "who": "卓琳（ch_zhuo_lin）", "what": "没有身份脸", "owner": "资产线", "shots": [1]}, story, looks, 1)
    job = AJ._new_job(RUN, 1, plan, {"who": "卓琳（ch_zhuo_lin）", "what": "没有身份脸"})
    AJ.save_job(root, job)
    j = AW.run_job(AJ.job_path(root, RUN, job["id"]), "gpu36:0", root, renderer=fake_renderer(root), cfg={**AW.config(root), "candidates": {"face": 2}})
    assert j["state"] == "done" and any("自动选用 s1100" in l for l in j["log"]), j["log"]
    face = _j(root / "assets_v2/manifest.json")["characters"]["ch_zhuo_lin"]["face"]
    assert face["file"].endswith("_s1100.png") and face["picked_by"].startswith("系统自动")
    req = next(r for r in _j(root / "data/owner_queue/requests.json") if r["id"] == job["pick_id"])
    assert req["auto_picked"] == "s1100" and req["title"].startswith("已自动选用：卓琳 身份脸") and "L-198" in req["detail"]
    assert AJ.registered_face(root, RUN, "ch_zhuo_lin")["sha256"] == face["sha256"]       # 设定图闸门此后放行
