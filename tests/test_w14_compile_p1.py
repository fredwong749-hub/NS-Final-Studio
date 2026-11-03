"""W14 COMPILE-P1（REVIEW-G4 两条 P1，sv18 第一批）
P1-1：frame_job.build_first 画布改稿路径（prompt_override）的风格后缀按本剧本段取（L-130），幻想段不再被拼上现实段后缀。
P1-2：tools/promptfix/cast_v2.py --render 退役（L-137 / PRODMERGE-O 一本账），只留 --compile / --check。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("packages/schema", "services/render_router", "services/agent", "packages/qc", "", "tools/promptfix"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

from ns_agent import asset_refs as AR  # noqa: E402

V2 = "series10_v2"
need_v2 = pytest.mark.skipif(not AR.manifest_rel(V2) or not (ROOT / AR.manifest_rel(V2)).is_file(), reason="V2 资产包清单缺")
FANTASY, REALITY = "【幻想段】", "【现实段】"


@pytest.fixture
def v2_shot(monkeypatch):
    """当前剧（V2）第 1 集里第一个 golden 认的女主单人镜；场景细节去掉段落标记，由各测试自己标"""
    monkeypatch.setenv("NS_RUN", V2)
    monkeypatch.setenv("NS_PRIMARY_RUN", V2)
    import golden_v2 as GV
    from ns_agent import cast_table as CT
    lead = CT.lead_id()
    names = (CT.speaker_cast(V2) or {}).get("names") or {}
    for n in range(1, 60):
        try:
            sc, ep, sh = GV.load_imported(n)
        except (SystemExit, StopIteration):
            continue
        if {names.get(c.name, c.name) for c in sh.cast if c.visible} != {lead}:
            continue
        base = (sh.scene_detail or "").replace(FANTASY, "").replace(REALITY, "")
        return sc, ep, sh.model_copy(update={"scene_detail": base})
    pytest.skip("当前剧第 1 集没有女主单人镜")


def _override(job_prompt_free: str, suffix: str | None) -> str:
    return f"{job_prompt_free}，{suffix}" if suffix else job_prompt_free


BODY = "中景，她站在窗边回头看向画面右侧，改稿测试正文"


# ---------------------------------------------------------------- P1-1
@need_v2
def test_p1_1_fantasy_override_keeps_only_fantasy_suffix(v2_shot):
    """幻想段镜头画布改稿（改稿里已带幻想段后缀）：不再判“没有后缀”而补一句现实段后缀"""
    from ns_agent import frame_job as FJ
    from ns_agent.gen_contract import style as ST
    sc, ep, sh = v2_shot
    sh = sh.model_copy(update={"scene_detail": FANTASY + (sh.scene_detail or "")})
    fan, rea = ST.preset_suffix(V2, "fantasy"), ST.preset_suffix(V2, "reality")
    assert fan != rea
    job = FJ.build_first(V2, ep, sh, sc.globals, prompt_override=_override(BODY, ST.image_suffix(V2, "fantasy")))
    assert job["style_segment"] == "fantasy" and job["preset"] == "v2_editorial_fantasy_c"
    assert job["prompt"].count(fan) == 1 and rea not in job["prompt"], job["prompt"]
    assert FANTASY not in job["prompt"]
    # 改稿没带后缀 → 补的是本段（幻想段）后缀
    job2 = FJ.build_first(V2, ep, sh, sc.globals, prompt_override=BODY)
    assert job2["prompt"].count(fan) == 1 and rea not in job2["prompt"], job2["prompt"]


@need_v2
def test_p1_1_reality_override_keeps_only_reality_suffix(v2_shot):
    from ns_agent import frame_job as FJ
    from ns_agent.gen_contract import style as ST
    sc, ep, sh = v2_shot
    sh = sh.model_copy(update={"scene_detail": REALITY + (sh.scene_detail or "")})
    fan, rea = ST.preset_suffix(V2, "fantasy"), ST.preset_suffix(V2, "reality")
    job = FJ.build_first(V2, ep, sh, sc.globals, prompt_override=_override(BODY, ST.image_suffix(V2, "reality")))
    assert job["style_segment"] == "reality" and job["preset"] == "v2_editorial_reality_c2"
    assert job["prompt"].count(rea) == 1 and fan not in job["prompt"], job["prompt"]
    job2 = FJ.build_first(V2, ep, sh, sc.globals, prompt_override=BODY)
    assert job2["prompt"].count(rea) == 1 and fan not in job2["prompt"], job2["prompt"]
    assert REALITY not in job2["prompt"]


def test_p1_1_override_path_passes_project_and_segment():
    """源码守卫：改稿分支不再用不带剧 / 段的 preset_suffix() / image_suffix()"""
    src = (ROOT / "services/agent/ns_agent/frame_job.py").read_text(encoding="utf-8")
    i = src.index("def build_first(")
    seg = src[i:src.index("\ndef ", i + 10)]
    assert "ST.preset_suffix()" not in seg and "ST.image_suffix()" not in seg
    assert "ST.preset_suffix(project, seg_in)" in seg and "ST.image_suffix(project, seg_in)" in seg


# ---------------------------------------------------------------- P1-2
def _cast():
    import cast_v2 as CV
    return CV


def test_p1_2_cast_v2_render_retired(capsys):
    CV = _cast()
    assert CV.main(["ch_tang_yao", "--render"]) == 3
    err = capsys.readouterr().err
    assert "已退役" in err and "producer.py" in err


def test_p1_2_cast_v2_has_no_second_render_ledger():
    src = (ROOT / "tools/promptfix/cast_v2.py").read_text(encoding="utf-8")
    for bad in ("def render(", "UF._run", "takes.jsonl", '"ab"', '"review_pages"', "shutil", "ComfyClient",
                "def vlm_check(", "def age_check(", "def ocr_check(", "anomaly"):
        assert bad not in src, bad
    assert 'mode="setting_candidate"' in src                        # 编译仍走 build_first + 正式设定候选 preflight


def test_p1_2_cast_v2_compile_and_check_exit_codes(monkeypatch, capsys):
    CV = _cast()

    class PF:
        def __init__(self, ok):
            self.ok = ok

        def reasons(self):
            return [] if self.ok else ["I7 测试不过"]

    job = {"prompt": "测试提示词", "refs": [], "preset": None, "compile_trace": {}}
    monkeypatch.setattr(CV, "compile_job", lambda cid: job)
    monkeypatch.setattr(CV, "preflight", lambda j, lane, cid: PF(False))
    assert CV.main(["ch_tang_yao", "--check"]) == 1
    assert CV.main(["ch_tang_yao", "--compile"]) == 0
    assert CV.main(["ch_tang_yao"]) == 0
    monkeypatch.setattr(CV, "preflight", lambda j, lane, cid: PF(True))
    assert CV.main(["ch_tang_yao", "--check"]) == 0
    assert "测试提示词" in capsys.readouterr().out
