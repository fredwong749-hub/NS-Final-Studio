"""PROMPTFIX 11-02（ALIGNMENT 第 2–6 步）编译层断言：K-REN-950 送脸 / 矛盾检出、951 局部人物服装范围、952 站位结构化、
953 尾帧送脸、954 种子流、955 手部单品不进参考槽。fb-0004..0007 + ep07-S3 尾帧陌生人。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("packages/schema", "services/render_router", "services/agent", "packages/qc", "tools/vqa", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import asset_refs as AR  # noqa: E402
from ns_agent import frame_job as FJ  # noqa: E402


# ---------------------------------------------------------------- 纯函数
def test_face_exposure_conflict_sizes():
    assert AR.face_exposure_conflict("近景", None)
    assert AR.face_exposure_conflict("中近景", "face")
    assert AR.face_exposure_conflict("中景", None)
    assert not AR.face_exposure_conflict("近景", "part")        # 局部特写：靠裁切保证不露脸
    assert not AR.face_exposure_conflict("特写", None)
    assert not AR.face_exposure_conflict(None, None)


def _shot(cast, img="近景，平视"):
    return {"index": 1, "episode": 1, "img_prompt": img, "cast": cast}


def test_part_scope_zones():
    sh = _shot([{"name": "林晚", "presence": "局部", "part": "肩后", "x": "左"}])
    assert AR.part_scope_zones(sh, "林晚") == {"neck"}
    sh = _shot([{"name": "顾沉", "presence": "局部", "part": "手", "x": "右"}])
    assert AR.part_scope_zones(sh, "顾沉") == {"hand"}
    sh = _shot([{"name": "顾沉", "presence": "局部", "part": None, "x": "右"}])
    assert AR.part_scope_zones(sh, "顾沉") == set()


def test_blocking_note_from_cast():
    sh = _shot([{"name": "林晚", "presence": "局部", "part": "肩头", "x": "中"},
                {"name": "阿岚", "presence": "局部", "part": "手", "x": "右"}])
    n = AR.blocking_note(sh, "近景，阿岚戴皮手套的手握着记号笔")
    assert n == "站位：林晚在画面中央（只露肩头），阿岚在画面右侧（只露手）（按此左右站位，不互换）。"
    assert AR.BLOCKING_NOTE_RE.search(n)
    # 正文已写每个人的画面左右 → 不重复
    assert AR.blocking_note(sh, "林晚在画面中央，阿岚在画面右侧伸手") == ""
    # 单人 / 同侧 → 不加
    assert AR.blocking_note(_shot([{"name": "林晚", "presence": "在画", "x": "左"}]), "") == ""
    # “中”景深不写成“中景”（易和景别混淆）
    sh = _shot([{"name": "顾沉", "presence": "在画", "x": "右", "depth": "中"},
                {"name": "林晚", "presence": "局部", "part": "肩后", "x": "左"}])
    assert "中景" not in AR.blocking_note(sh, "")


def test_blocking_note_registered_for_stale_matcher():
    assert AR.BLOCKING_NOTE_RE in AR.TEXT_NOTE_RES


def test_seed_stream_never_reuses_and_is_deterministic():
    from ns_render import seed_stream as SS
    s1, i1 = SS.pick("ep07-S3", "last", 1, [])
    s1b, _ = SS.pick("ep07-S3", "last", 1, [])
    assert s1 == s1b                                             # 同账本同次数 → 两台同一颗
    takes = [{"stage": "last", "seed": s1}]
    s2, i2 = SS.pick("ep07-S3", "last", 1, takes)               # 下一轮又从第 1 次数起：跳过用过的
    assert s2 != s1 and i2["skipped"] == 1
    used = {s1, s2}
    s3, _ = SS.pick("ep07-S3", "last", 1, [{"stage": "last", "seed": x} for x in used])
    assert s3 not in used
    assert SS.pick("ep07-S3", "image", 1, takes)[0] != s2       # 首帧 / 尾帧各一条流


def test_seed_stream_ep07_s3_history():
    """ep07-S3 尾帧 v14–v19 实际种子（旧做法：v16 = v19 = 271940492627291）：新流不再出这些种子"""
    from ns_render import seed_stream as SS
    old = [253708524697205, 110292634263597, 271940492627291]
    takes = [{"stage": "last", "seed": s} for s in old * 2]
    seen = set(old)
    for att in (1, 2, 3):
        s, _ = SS.pick("ep07-S3", "last", att, takes)
        assert s not in seen
        takes.append({"stage": "last", "seed": s})
        seen.add(s)


def test_anomaly_blocking_defects():
    import anomaly as A
    heads = [{"box": [50, 100, 150, 220], "sims": {"lin_wan": 0.6}}]      # 脸中心 0.13 W（左）
    cast = [{"name": "林晚", "x": "中"}]
    d = A.blocking_defects(heads, cast, 768)
    assert d and d[0]["code"] == "blocking_mismatch"
    assert A.blocking_defects(heads, [{"name": "林晚", "x": "左"}], 768) == []
    assert A.blocking_defects(heads, [{"name": "林晚", "x": None}], 768) == []


# ---------------------------------------------------------------- 真剧本（series10）编译断言
FIXTURE = ROOT / "tests" / "fixtures" / "promptfix" / "series10_v1_subset.json"
PROJECT = "series10_v1"


@pytest.fixture(scope="module")
def S():
    """固定夹具：series10_v1 导入稿冻结子集（8 镜）+ 资产项目 series10_v1；不随现行主剧（V2）切换而跳过"""
    from ns_schema.script import ScriptImport
    s = ScriptImport.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    assert AR.project_cfg(PROJECT), "series10_v1 资产项目登记缺失"
    shots = {f"ep{int(e.number):02d}-S{sh.index}": (e, sh) for e in s.episodes for sh in e.shots}

    def job(sid):
        ep, sh = shots[sid]
        return FJ.build_first(PROJECT, ep, sh, s.globals), sh
    return job


def test_fb0007_partial_woman_no_wardrobe_on_man(S):
    """ep08-S5：林晚局部（肩后、不露脸）→ 不送她的设定图 / 整套板，正文不补“林晚本镜造型…要穿全”"""
    job, _sh = S("ep08-S5")
    slots = job["asset_refs"]["slots"]
    assert not any(s["character"] == "lin_wan" and s["kind"] in ("board", "sheet") for s in slots)
    assert "林晚本镜造型" not in job["prompt"] and "漆皮长风衣" not in job["prompt"]
    assert job["compile_trace"]["wardrobe_scope"].get("林晚") == ["neck"]
    assert "站位：顾沉在画面右侧" in job["prompt"] and "林晚在画面左侧" in job["prompt"]


def test_fb0007_switch_off_restores_old(S, monkeypatch):
    monkeypatch.setattr(AR, "pf_on", lambda k: False)
    job, _sh = S("ep08-S5")
    assert any(s["character"] == "lin_wan" and s["kind"] in ("board", "sheet") for s in job["asset_refs"]["slots"])
    assert "站位：" not in job["prompt"]


def test_fb0006_hand_item_not_in_slots(S):
    """ep07-S12 中近景：指甲单品图是两只手的照片 → 不进参考槽（K-REN-955）"""
    job, _sh = S("ep07-S12")
    labels = [lab for s in job["asset_refs"]["slots"] for lab in s.get("labels") or []]
    assert not any("指甲" in lab for lab in labels)
    assert any(w.get("rule") == "K-REN-955" for w in job["asset_refs"]["warnings"])


def test_k950_all_partial_uses_crop_not_face(S):
    """ep05-S3：在画的人全是局部 → K-REN-903 局部构图首句是结构化保证（903 上线后 v86–v92 没再出脸），不改成送脸"""
    job, _sh = S("ep05-S3")
    assert not job["compile_trace"]["conflicts"]
    assert "画面上沿在下颌以下" in job["prompt"]


def test_k950_partial_with_onscreen_partner_sends_face(S):
    """ep01-S8：林晚在画、顾沉局部（手）、景别不是局部特写 → 报矛盾、送顾沉的脸，且正文不再写“顾沉只露出…不露脸”"""
    job, _sh = S("ep01-S8")
    assert job["compile_trace"]["conflicts"], "冻结夹具里 ep01-S8 必须检出 cast_face_conflict"
    assert "顾沉只露出" not in job["prompt"] and "顾沉不露脸" not in job["prompt"]


def test_k953_last_frame_face_when_end_state_shows_face(S):
    """ep07-S3：首帧腰部局部（不送脸），尾帧“她下唇松开，嘴角放松，视线抬起” → 尾帧必须送林晚身份脸"""
    job, _sh = S("ep07-S3")
    assert not job["face_files"]
    last = FJ.build_last(job, "data/x_first.png")
    assert len(last["refs"]) == 2 and last["refs"][1] == AR.face_of(job["framing_project"], "lin_wan")
    assert last["prompt"].startswith("图2是林晚的脸部参考")
    assert last["compile_trace"]["last_faces"][0]["character"] == "lin_wan"


def test_trace_sha_deterministic(S):
    a, _ = S("ep01-S1")
    b, _ = S("ep01-S1")
    assert a["compile_trace"]["prompt_sha"] == b["compile_trace"]["prompt_sha"]
    assert a["compile_trace"]["refs_sha"] == b["compile_trace"]["refs_sha"]
    assert all(r["sha"] for r in a["compile_trace"]["refs"])


# ---------------------------------------------------------------- K-REN-956 先验收、后重出（编译变化不作废已通过的版本）
def _producer():
    import importlib.util
    spec = importlib.util.spec_from_file_location("producer_pf", ROOT / "tools" / "autopilot" / "producer.py")
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
    spec.loader.exec_module(m)
    return m


def test_k956_compile_change_does_not_requeue():
    PR = _producer()
    assert PR.stale_requeue_reasons(["编译器升级"]) == []
    # DEBUG-RSI 合并后为白名单（STALE_REQUEUE_ON，只有人主动改的才重出）：编译变化一律不作废
    assert "image" not in PR.stale_requeue_map({"image": ["编译器升级"]})
    on = PR.STALE_REQUEUE_ON[0]
    assert PR.stale_requeue_reasons([on, "编译器升级"]) == [on]


def test_k956_e24_only_input_sig(monkeypatch):
    PR = _producer()
    fo = {"status": "passed", "take": 3}
    # 作业签名变了（编译规则变）但剧本输入签名没变 → 不作废
    monkeypatch.setattr(PR, "job_sig", lambda p, s: "NEW")
    monkeypatch.setattr(PR, "input_sig", lambda p, s: "IN1")
    assert PR.first_input_changed(None, "ep01-S1", fo, {"passed_sig": "OLD", "passed_input_sig": "IN1"})["status"] == "passed"
    # 旧数据没记 passed_input_sig → 不动
    assert PR.first_input_changed(None, "ep01-S1", fo, {"passed_sig": "OLD"})["status"] == "passed"
    # 剧本输入真改了 → 回到 ready
    monkeypatch.setattr(PR, "input_sig", lambda p, s: "IN2")
    assert PR.first_input_changed(None, "ep01-S1", fo, {"passed_sig": "OLD", "passed_input_sig": "IN1"})["status"] == "ready"


def test_k956_input_sig_ignores_compile_output():
    PR = _producer()
    from types import SimpleNamespace
    p = SimpleNamespace(root=ROOT)
    s1 = PR.input_sig(p, "ep01-S1")
    assert s1 and s1 == PR.input_sig(p, "ep01-S1")


# ---------------------------------------------------------------- K-REN-957 背影 / 远景人物
def test_k957_back_in_text_own_clause_only():
    img = "林晚站在画面左侧，视线朝走廊；顾沉的背影在画面右侧远处，背对镜头朝走廊暗处走"
    assert AR.back_in_text("顾沉", img, ["林晚", "顾沉"])
    assert not AR.back_in_text("林晚", img, ["林晚", "顾沉"])


def test_k957_ep01_s9_back_person_no_face(S):
    """ep01-S9：顾沉 cast 在画｜右｜后，剧本写背影 → 不送正脸、送背面设定图、首句不写“两张脸都清晰入画”、加层次句"""
    job, _sh = S("ep01-S9")
    assert "gu_chen" not in job["compile_trace"]["faces"]
    assert any("back_nohead" in f for f in job["refs"])
    assert "两张脸都清晰入画" not in job["prompt"]
    assert "层次：顾沉在后景，背对镜头的背影，人物较小、离镜头远（远小近大）" in job["prompt"]
    assert AR.LAYER_NOTE_RE in AR.TEXT_NOTE_RES


def test_k957_switch_off(S, monkeypatch):
    real = AR.pf_on
    monkeypatch.setattr(AR, "pf_on", lambda k: False if k == "back_view_guard" else real(k))
    job, _sh = S("ep01-S9")
    assert "gu_chen" in job["compile_trace"]["faces"]
