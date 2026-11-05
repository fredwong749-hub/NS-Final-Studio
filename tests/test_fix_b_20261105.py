"""FIX-B 11-05（REVIEW-B / REVIEW-C 复审意见）：时间戳 JST、卡点登记保字节、old blocker 带时区比较、scorecard 取已部署版本、
并列主语、K-WRT-813 与 L-192 六种同步、两条视频路同一判段、resident_guard 重启退避、episode_timeline JST。
（cut 互斥 / manifest 必须有 pin 的测试在 test_system_version.py / test_release_manifest.py）"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "packages" / "schema"), str(ROOT / "services" / "agent"), str(ROOT / "services" / "recipes"),
                str(ROOT / "services" / "api"), str(ROOT / "tools")]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------- 2 report_issue / sop
def test_report_issue_jst_and_preserves_bytes(tmp_path, monkeypatch):
    RI = _load("tools/master/report_issue.py", "report_issue_fixb")
    monkeypatch.setenv("TZ", "America/New_York")
    live = tmp_path / "V2_LIVE.md"
    live.write_bytes("# 标题\r\n旧行1\r\n旧行2 \xff坏字节\r\n".encode("utf-8", errors="surrogateescape") if False else b"# \xe6\xa0\x87\xe9\xa2\x98\r\nold1\r\nbad \xff byte\r\n")
    rec = RI.report("series10_v2", 1, "8", "T", "说明", True, issues=tmp_path / "i.jsonl", live=live)
    assert rec["time"].endswith("+09:00") and re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\+09:00$", rec["time"])
    raw = live.read_bytes()
    assert raw.startswith(b"# \xe6\xa0\x87\xe9\xa2\x98\r\n") and raw.endswith(b"old1\r\nbad \xff byte\r\n")     # CRLF / 坏字节原样
    assert raw.count(b"\r\n") == 4 and b"\n" not in raw.replace(b"\r\n", b"")                                  # 插入行也是 CRLF，没有混入裸 LF
    assert rec["id"] in raw.decode("utf-8", errors="replace")
    # LF 文件保持 LF
    live2 = tmp_path / "L2.md"
    live2.write_bytes(b"head\nold\n")
    RI._insert_live("x", live2)
    assert live2.read_bytes() == b"head\nx\nold\n"


def test_sop_old_blocker_compares_with_timezone():
    import ns_api.sop as SOP
    # 卡点带 +09:00，import_at 无时区（= JST）：同一时刻不判旧、早一分钟判旧；带别的时区按其自身折算
    assert SOP._is_older("2026-11-05 10:00:00+09:00", "2026-11-05 10:00:01") is True
    assert SOP._is_older("2026-11-05 10:00:01+09:00", "2026-11-05 10:00:00") is False
    assert SOP._is_older("2026-11-05 00:30:00+00:00", "2026-11-05 10:00:00") is True        # 00:30Z = 09:30 JST < 10:00 JST
    assert SOP._is_older("2026-11-05 00:30:00+00:00", "2026-11-05 09:00:00") is False       # 09:30 JST > 09:00 JST
    assert SOP._is_older("乱码", "2026-11-05 10:00:00") is False and SOP._is_older(None, "2026-11-05 10:00:00") is False


# ---------------------------------------------------------------- 3 scorecard
def test_scorecard_current_sv_prefers_deployed(monkeypatch):
    SC = _load("tools/sentinel/scorecard.py", "scorecard_fixb")
    files = {"data/system_version.txt": {"id": "sv-20261105-05"},
             "data/system_versions/index.json": {"versions": [{"id": "sv-20261105-05", "deployed": {"gpu33": 1}}, {"id": "sv-20261105-09", "deployed": {}},
                                                              {"id": "sv-20261105-10", "deployed": {}}]}}
    monkeypatch.setattr(SC, "jl", lambda p, default=None: files.get(p, default))
    monkeypatch.setattr(SC, "_run", lambda a, t: "sv-20261105-10\nsv-20261105-09")
    assert SC.current_sv() == "sv-20261105-05"                      # 已部署版本优先，不被未部署的新 tag 盖过
    files["data/system_version.txt"] = {}
    files["data/system_versions/index.json"] = {"versions": [{"id": "sv-20261105-09", "deployed": {}}]}
    assert SC.current_sv() == "sv-20261105-10"                      # 都没部署：退回 tag（deployed=false）


# ---------------------------------------------------------------- 7 episode_timeline
def test_episode_timeline_generated_at_is_jst():
    s = (ROOT / "tools/master/episode_timeline.py").read_text(encoding="utf-8")
    assert "datetime.now(timezone(timedelta(hours=9)))" in s and "datetime.now().isoformat" not in s


# ---------------------------------------------------------------- 8 并列主语
def test_coordinated_subjects_back_to_camera():
    from ns_agent import asset_refs as AR
    names = ["卓琳", "祁念", "顾沉"]
    assert AR.clause_subjects("卓琳和祁念背对镜头", names) == ("卓琳", "祁念")
    assert AR.clause_subjects("卓琳与祁念和顾沉并排", names) == ("卓琳", "祁念", "顾沉")
    assert AR.clause_subjects("卓琳对祁念和顾沉说", names) == ("卓琳",)            # 动词后的 和 = 宾语介词
    assert AR.clause_subjects("卓琳蹲在祁念左前", names) == ("卓琳",)
    assert AR.clause_subject("卓琳蹲在祁念左前、背对镜头", names) == "卓琳"
    assert AR.back_in_text("祁念", "卓琳和祁念背对镜头站在桥上", ["卓琳"]) is True
    assert AR.back_in_text("卓琳", "卓琳和祁念背对镜头站在桥上", ["祁念"]) is True
    assert AR.back_in_text("祁念", "卓琳蹲在祁念左前、背对镜头", ["卓琳"]) is False
    from script_rsi import staging as SG
    assert SG._face_hidden("祁念", ["卓琳和祁念背对镜头"], names) is True
    assert SG._face_hidden("祁念", ["卓琳蹲在祁念左前", "背对镜头"], names) is False


# ---------------------------------------------------------------- 9 K-WRT-813
def test_k_wrt_813_matches_l192_six_moves():
    import yaml
    rules = yaml.safe_load((ROOT / "knowledge/rules/writer_camera.yaml").read_text(encoding="utf-8"))
    rules = rules if isinstance(rules, list) else rules.get("rules") or rules
    r = next(x for x in rules if x["id"] == "K-WRT-813")
    cm = yaml.safe_load((ROOT / "config/director/camera_moves.yaml").read_text(encoding="utf-8"))
    for txt in (r["then"], r["writer_text"]):
        for mv in ("static", "push_in", "pull_out", "bolt_push_settle", "handheld_follow", "pedestal_up"):
            assert mv in txt or {"static": "固定", "push_in": "推近", "pull_out": "拉远", "pedestal_up": "升"}.get(mv, "") in txt, (mv, txt[:80])
        assert "升降" not in txt.split("不要写")[0] and "L-192" in txt
        assert "多人" in txt or "2 个以上" in txt
    assert cm  # 词表在
    gen = (ROOT / "config/recipes/writer_knowledge.md").read_text(encoding="utf-8")
    assert "pedestal_up" in gen and "L-192 起六种 enabled" in gen or "现在六种（L-192）" in gen       # 已重编译


# ---------------------------------------------------------------- 10 判段一致
def test_video_segment_same_in_both_paths():
    from ns_agent.gen_contract import style as ST
    from ns_recipes import prompt_v2 as RPV2
    from ns_recipes.spec_import import specs_from_import
    from ns_schema.script import ScriptImport
    base = ROOT / "data/import/runs/series10_v2/script_v2.json"
    if not base.is_file():
        pytest.skip("series10_v2 导入稿缺")
    s = ScriptImport.model_validate_json(base.read_text(encoding="utf-8"))
    seen = set()
    for ep, idx in ((1, 2), (2, None)):
        e = next((x for x in s.episodes if x.number == ep), None)
        if e is None:
            continue
        specs = {x.index: x for x in specs_from_import(s, ep, with_assets=False)}
        for sh in e.shots:
            if idx is not None and sh.index != idx:
                continue
            want = ST.segment_of(sh)[0] or "reality"
            assert RPV2.segment_of(specs[sh.index]) == want, (ep, sh.index)
            seen.add((ep, sh.index))
    assert (1, 2) in seen and any(k[0] == 2 for k in seen)
    # 只有“幻想”字样、没有段落标记的 spec：ns_agent 判现实，这里也必须判现实（旧判法会判 fantasy）
    class _Spec:
        extras = {"画面": "他想起幻想里的海"}
        scene = type("S", (), {"detail": "走廊"})()
        first_frame = type("F", (), {"text": ""})()
        motion = type("M", (), {"text": ""})()
        h3 = type("H", (), {"text": ""})()
    assert RPV2.segment_of(_Spec()) == (ST.segment_of({"extras": _Spec.extras, "scene_detail": "走廊"})[0] or "reality") == "reality"


# ---------------------------------------------------------------- 5 resident_guard（静态：脚本文本）
def test_resident_guard_self_heal_has_backoff_and_pid_match():
    s = (ROOT / "ops/autostart/resident_guard.ps1").read_text(encoding="utf-8")
    f = s[s.index("function AutoflowWanted"):s.index("Log \"守护启动")]
    assert "$AfHealMax" in s and "AddHours(-1)" in f and "Pow(2" in f              # 每小时上限 + 指数退避
    assert "[int]$h.pid -eq [int]$hb.pid" in f and "-le 10" in f                 # health.json pid 与心跳 pid 一致 + 已运行 > 10 分钟
    assert "Move-Item $HealthFlag" in f and "Remove-Item" not in f              # 旗改名留账，不删
