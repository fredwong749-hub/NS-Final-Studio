"""OVERSIGHT-F P1-13a（STYLE-V2 11-02）：V2 的配乐 / 音色只从 config/music_v2.json / config/voices_v2.json 取，V1 内容进不来（L-126）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/post", "services/agent", "tools"):
    sys.path.insert(0, str(ROOT / p))

from ns_post import run_media as RM  # noqa: E402

V2, V1 = "series10_v2", "series10_v1"
PICKED = {"lead_f": "lead_f/b", "ch_li_an": "m1/b", "ch_zhou_xu": "m2/c", "ch_jiang_yubai": "m3/c",
          "ch_zhuo_lin": "zhuo_lin/c", "ch_tang_yao": "tang_yao/b"}   # L-132 + cast_voice；卓琳 c / 唐瑶 b = 项目方 11-02 23:55 在待办中心挑定（INBOXPICK-S replay）
UNVOICED: set[str] = set()                                                                              # 卓琳 / 唐瑶已选定，目前没有无音色的人


def test_v2_is_asset_pack_and_v1_is_not():
    assert RM.is_asset_pack_run(V2, ROOT) and not RM.is_asset_pack_run(V1, ROOT)


def test_v2_music_dir_never_v1():
    d = RM.music_dir(V2, ROOT)
    assert d.resolve() != (ROOT / "data/music/series10").resolve()
    assert d == ROOT / "data" / "music" / V2
    assert RM.music_dir(V1, ROOT) == ROOT / "data/music/series10"      # V1 行为不变


def test_v2_music_library_sha_checked():
    lib = RM.music_library(V2, ROOT)
    assert set(lib) == {"v2_bgm_A_reality", "v2_bgm_B_reality", "v2_bgm_C_fantasy"}   # L-131 三条
    assert all(not t["file"].startswith("data/music/series10/") for t in lib.values())


def test_v2_rejects_v1_bgm_in_cut_edit():
    with pytest.raises(RM.V2MediaError):
        RM.check_episode_music(V2, 1, RM.music_dir(V2, ROOT), "data/music/series10/ep01.wav", ROOT)


def test_v2_episode_bgm_must_reference_library(tmp_path, monkeypatch):
    (tmp_path / "ep01.json").write_text(json.dumps({"library_track": "not_registered"}), encoding="utf-8")
    with pytest.raises(RM.V2MediaError):
        RM.check_episode_music(V2, 1, tmp_path, None, ROOT)
    t = RM.music_library(V2, ROOT)["v2_bgm_C_fantasy"]
    (tmp_path / "ep01.json").write_text(json.dumps({"library_track": t["id"], "library_sha256": t["sha256"]}), encoding="utf-8")
    assert RM.check_episode_music(V2, 1, tmp_path, None, ROOT)["track"] == t["id"]


def test_v2_tts_only_registered_voices():
    from ns_post.tts import load_voice_config, voice_for
    cfg = load_voice_config(run=V2)
    assert {k: c["voice"] for k, c in cfg["characters"].items()} == PICKED
    assert "lin_wan" not in json.dumps(cfg["characters"], ensure_ascii=False)
    for k in PICKED:
        assert cfg["characters"][k]["ref_wav"].startswith("data/assets/voices_v2/")
        v = voice_for(cfg, k)[0]
        assert v.engine == "cosyvoice3_zs" and cfg["characters"][k]["ref_sha256"][:16] in v.model
    with pytest.raises(Exception):
        voice_for(cfg, "lin_wan")
    assert "lin_wan" in load_voice_config(run=V1)["characters"]        # V1 照旧


def test_v2_compose_does_not_read_v1_music(monkeypatch, tmp_path):
    """assemble_series.compose（成片 / 预览 / CUTEDIT 共用）对 V2 传给合成器的 music_dir 不是 data/music/series10，音色只有登记的 6 个"""
    import assemble_series as AS
    import ns_post.assemble as A
    import ns_post.tts as T
    seen = {}

    class _Dummy:
        def __init__(self, cfg, **k):
            seen.setdefault("cfgs", []).append(cfg)

    monkeypatch.setattr(T, "KokoroBackend", _Dummy)
    monkeypatch.setattr(T, "SenseVoiceAsr", _Dummy)
    monkeypatch.setattr(A, "load_episode", lambda path, ep: {"ep": ep})

    def fake_assemble(episode, work, **k):
        seen["settings"], seen["voices_cfg"] = k["settings"], k["voices_cfg"]
        return {"speech": []}

    monkeypatch.setattr(A, "assemble_episode", fake_assemble)
    AS.compose(1, {}, tmp_path, "t", run=V2)
    md = Path(seen["settings"].music_dir)
    assert md.resolve() != (ROOT / "data/music/series10").resolve() and md.name == V2
    assert set(seen["voices_cfg"]["characters"]) == set(PICKED)


def test_v2_api_music_dir_and_shot_audio_voices(monkeypatch):
    """界面侧：BGM 页 / 镜头试听在 V2 也只认 V2（bgm_api.music_dir、shot_audio 的音色按剧取）"""
    sys.path.insert(0, str(ROOT / "services" / "api"))
    from ns_api import bgm_api, run_paths as RP
    monkeypatch.setattr(RP, "current_run", lambda root=None: V2)
    d = bgm_api.music_dir()
    assert d.resolve() != (ROOT / "data/music/series10").resolve() and d.name == V2
    monkeypatch.setattr(RP, "current_run", lambda root=None: V1)
    assert bgm_api.music_dir().name in ("series10", "music")


# ---------------------------------------------------------------- OVERSIGHT-F 第 14 轮：不带 run 的 V1 入口一次堵死
def _as_current(monkeypatch, run):
    import ns_post.tts as T
    monkeypatch.setattr(T, "_current_run", lambda: run)
    return T


def test_load_voice_config_without_run_fails_closed_on_v2(monkeypatch):
    T = _as_current(monkeypatch, V2)
    with pytest.raises(T.VoiceRunRequired):
        T.load_voice_config()
    with pytest.raises(T.VoiceRunRequired):
        T.load_voice_config(ROOT / "config" / "voices.json")          # 显式指向 V1 音色表也不行
    assert set(T.load_voice_config(run=V2)["characters"]) == set(PICKED)
    T = _as_current(monkeypatch, V1)
    assert "lin_wan" in T.load_voice_config()["characters"]          # V1 照旧


def test_v2_voiceover_and_preflight_never_fall_back_to_lin_wan(monkeypatch):
    T = _as_current(monkeypatch, V2)
    cfg = T.load_voice_config(run=V2)
    assert T.default_voiceover_speaker(cfg) == "lead_f"
    bad = {**cfg, "voiceover_speaker": "nobody"}
    with pytest.raises(T.TtsError):
        T.default_voiceover_speaker(bad)
    with pytest.raises(T.VoiceRunRequired):
        T.default_voiceover_speaker()                                 # 不带 cfg / run：V2 失败关闭
    miss = T.tts_preflight()                                          # 不带 run：报缺，不退回 V1 音色表
    assert miss and "资产包模式" in miss[0]


def test_resolve_episode_narrator_from_run_cfg(monkeypatch):
    T = _as_current(monkeypatch, V2)
    from ns_post import speakers as S
    ep = {"number": 1, "shots": [{"index": 1, "voiceover": {"text": "今天的外滩风有点大。"}, "dialogue": []}]}
    cfg = T.load_voice_config(run=V2)
    lines = S.resolve_episode(ep, cfg.get("line_overrides"), narrator=T.default_voiceover_speaker(cfg))
    assert lines and all(ln.speaker != "lin_wan" for ln in lines)


def test_assemble_episode_tool_refuses_v2(monkeypatch):
    _as_current(monkeypatch, V2)
    import assemble_episode as AE
    why = AE.guard_asset_pack_run()
    assert why and "assemble_series.py" in why
    _as_current(monkeypatch, V1)
    assert AE.guard_asset_pack_run() is None


def test_bgm_api_candidates_dir_and_choose_by_run(monkeypatch):
    sys.path.insert(0, str(ROOT / "services" / "api"))
    from fastapi import HTTPException
    from ns_api import bgm_api, run_paths as RP
    monkeypatch.setattr(RP, "current_run", lambda root=None: V2)
    assert bgm_api._ep_dir(3) == ROOT / "data" / "music" / V2 / "ep03"
    monkeypatch.setattr(bgm_api, "require_owner", lambda request: {"name": "t", "role": "owner"})
    with pytest.raises(HTTPException) as e:
        bgm_api.choose(3, bgm_api.ChooseBody(id="r1_c1"), request=None)
    assert e.value.status_code == 409                                  # V2 不走 deliver（会写 V1 目录）
    monkeypatch.setattr(RP, "current_run", lambda root=None: V1)
    assert bgm_api._ep_dir(3).parent.name in ("series10", "music")



# ---------------------------------------------------------------- 总调度 22:4x：V2 说话人归属走 cast_table（P1 人物表）
def _v2_cfg():
    from ns_post.tts import load_voice_config
    return load_voice_config(run=V2)


def test_v2_voices_only_the_four_picked_and_unvoiced_raise():
    from ns_post.tts import TtsError, voice_for
    cfg = _v2_cfg()
    assert {cfg["characters"][k]["voice"].split("/")[0] for k in cfg["characters"]} == {"lead_f", "m1", "m2", "m3", "zhuo_lin", "tang_yao"}
    assert set(cfg["unvoiced"]) == UNVOICED
    with pytest.raises(TtsError):                       # 没登记的人依旧报错，不拿别人顶替
        voice_for(cfg, "ch_not_registered")
    lead_sha = cfg["characters"]["lead_f"]["ref_sha256"]
    assert all(c["ref_sha256"] != lead_sha for k, c in cfg["characters"].items() if k != "lead_f")   # 没人拿女主顶替


def test_v2_cast_comes_from_cast_table():
    from ns_agent import cast_table as CT
    cfg = _v2_cfg()
    assert cfg["cast"]["names"] == CT.speaker_cast(V2)["names"]
    assert cfg["cast"]["names"]["祁念"] == "lead_f" and cfg["cast"]["lead"] == "lead_f"


def _ep(*shots):
    return {"number": 1, "shots": [{"index": i + 1, **sh} for i, sh in enumerate(shots)]}


def test_v2_speaker_attribution_by_p1_names():
    from ns_post.speakers import Cast, resolve_episode
    cfg = _v2_cfg()
    cast = Cast.from_cfg(cfg)
    ep = _ep({"dialogue": [{"speaker_note": "黎岸", "text": "钥匙在你手里。"},
                           {"speaker_note": "她", "text": "我知道。"},
                           {"speaker_note": "他，低声", "text": "那就留下。"}]},
             {"dialogue": [{"speaker_note": "江予白", "text": "再来一张。"}, {"speaker_note": "周序", "text": "我在楼下。"}]})
    lines = resolve_episode(ep, {}, narrator="lead_f", cast=cast)
    assert [ln.speaker for ln in lines] == ["ch_li_an", "lead_f", "ch_li_an", "ch_jiang_yubai", "ch_zhou_xu"]
    assert all(ln.speaker not in ("lin_wan", "gu_chen", "chen_yu") for ln in lines)


def test_v2_unknown_he_is_error_not_gu_chen():
    from ns_post.speakers import Cast, UnresolvedSpeaker, resolve_episode
    cast = Cast.from_cfg(_v2_cfg())
    with pytest.raises(UnresolvedSpeaker):
        resolve_episode(_ep({"dialogue": [{"speaker_note": "他", "text": "走吧。"}]}), {}, narrator="lead_f", cast=cast)


def test_v2_supporting_female_line_raises_at_voice():
    from ns_post.speakers import Cast, resolve_episode
    from ns_post.tts import TtsError, voice_for
    cfg = _v2_cfg()
    [ln] = resolve_episode(_ep({"dialogue": [{"speaker_note": "卓琳", "text": "合同在我这儿。"}]}), {}, narrator="lead_f",
                           cast=Cast.from_cfg(cfg))
    assert ln.speaker == "ch_zhuo_lin"
    assert voice_for(cfg, ln.speaker)[0].name == "zhuo_lin/c"     # 卓琳已选定音色（原来这里应报错）


def test_v1_cast_unchanged():
    from ns_post.speakers import V1_CAST, Cast
    assert Cast.from_cfg({"characters": {}}) is V1_CAST and V1_CAST.lead == "lin_wan" and V1_CAST.default_male == "gu_chen"
