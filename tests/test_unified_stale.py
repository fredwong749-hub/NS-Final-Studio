"""DATAALIGN 2026-11-01（UIPIXEL P1）：唯一出图路径（unified_frame）刚出的版本不能被标“剧本已改 / 过期”。
用真实剧本：拿第一个登记了资产的镜头，按 unified 路径现在会拼出的正文造一个版本（前面加槽位标注），过期判定必须为空；
正文换一句（模拟剧本改了、输入签名也变了）→ 必须判过期（local），不能静默。"""
import pytest


def _first_shot(APP):
    from ns_api import unified_stale as UST
    for ep in APP._script.episodes:
        for s in ep.shots:
            ub = UST.unified_bodies(APP._script, ep, s)
            if ub:
                return ep, s, ub
    pytest.skip("当前剧本不属于登记了资产的项目（没有 unified 出图路径）")


def _take(prompt, inputs_sha):
    return {"n": 99, "stage": "image", "workflow": "frame_v9_unified", "prompt": prompt, "created_at": "2099-01-01T00:00:00",
            "inputs_sha": inputs_sha, "look_hash": None}


def test_fresh_unified_take_not_stale():
    from ns_api import app as APP
    from ns_agent.state_timeline import shot_inputs_sha
    ep, s, ub = _first_shot(APP)
    edit = APP.P.load_edit(s.id)
    compiled = APP._compile_for_display(ep, s, edit)
    take = _take("图1是某某的脸部参考（只取脸和发型）。" + ub["image"], shot_inputs_sha(s.id, APP.P.ROOT))
    local, glob = APP._stale_split(s.id, take, s, compiled, edit, {"image": None, "last": None, "video": None}, None, "")
    assert "剧本已改" not in local and not local, (local, glob)


def test_changed_unified_take_is_stale():
    from ns_api import app as APP
    ep, s, ub = _first_shot(APP)
    edit = APP.P.load_edit(s.id)
    compiled = APP._compile_for_display(ep, s, edit)
    take = _take("图1是某某的脸部参考。" + ub["image"].replace("，", "，旧句子，", 1), "0000000000000000")
    local, _glob = APP._stale_split(s.id, take, s, compiled, edit, {"image": None, "last": None, "video": None}, None, "")
    assert local, "正文和输入签名都变了，必须判过期"


def test_frames_v2_recipe_counts_as_unified():
    """ASSETMASTER frames_v2 登记的 frame_v9 版本（workflow=series_pipeline，params.origin.recipe=frame_v9）同样按 unified 正文判"""
    from ns_api import unified_stale as UST
    assert UST.is_unified({"workflow": "series_pipeline", "params": {"origin": {"recipe": "frame_v9"}}})
    assert not UST.is_unified({"workflow": "series_pipeline", "params": {"origin": {"run": "series10_v1"}}})
    assert not UST.is_unified({"workflow": "qwen_two_stage", "params": None})


def test_pipeline_last_take_is_current_last_frame(monkeypatch):
    """PW-011：登记进来的尾帧（source=pipeline）就是当前尾帧：last_frame_target 不能是 null，来源按“生成”"""
    from ns_api import app as APP
    from ns_schema.edits import ShotEdit
    monkeypatch.setattr(APP, "_url", lambda rel: f"/files/{rel}" if rel else None)
    sid = APP._script.episodes[0].shots[0].id
    act = {"image": None, "video": None, "last": {"n": 1, "file": "renders/x/last_001_pipeline.png", "source": "pipeline"}}
    lf = APP._last_frame_info(sid, ShotEdit(), act)
    assert lf["last_frame_target"] == "/files/renders/x/last_001_pipeline.png" and lf["last_frame_source"] == "gen"


def test_unified_take_with_slot_shortage_note_not_stale():
    """11-01 ep06-S7 #2：参考槽不足时 frame_job.with_note 把“X的服装、鞋、饰品按文字描述（参考槽不足）”插在正文末尾、
    风格后缀之前；过期判定要用同一个 with_note 放回去再比，不能误报“编译器升级”"""
    from ns_agent import frame_job as FJ
    from ns_api import app as APP
    from ns_agent.state_timeline import shot_inputs_sha
    ep, s, ub = _first_shot(APP)
    edit = APP.P.load_edit(s.id)
    compiled = APP._compile_for_display(ep, s, edit)
    body = FJ.with_note(ub["image"], "顾沉的服装、鞋、饰品按文字描述（参考槽不足）。")
    assert body != ub["image"]
    take = _take("图1是某某的脸部参考（只取脸和发型）。" + body, shot_inputs_sha(s.id, APP.P.ROOT))
    local, glob = APP._stale_split(s.id, take, s, compiled, edit, {"image": None, "last": None, "video": None}, None, "")
    assert not local and not glob, (local, glob)
