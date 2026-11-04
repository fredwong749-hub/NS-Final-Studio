"""L-188：L1 提示词验收脚本 + 融合句 / V2 风格后缀不含被 L1 禁掉的句子"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "qa"))
import l1_prompt_audit as A  # noqa: E402


def test_scan_banned_and_l1():
    b, l1 = A.scan("光线：正面高亮，one continuous depth of field", "reality")
    assert b == ["正面高亮", "one continuous depth"] and l1 == []
    b, l1 = A.scan("顶灯上侧 45° 主光，黑旗负补光", "reality")
    assert b == [] and "黑旗" in l1
    assert A.scan("暖金高调", "fantasy") == ([], ["暖金"])
    assert A.scan("暖金高调", "reality")[1] == []        # 现实段不认幻想段的暖金


def test_fusion_and_v2_suffix_clean():
    import yaml
    cfg = yaml.safe_load((ROOT / "config/director/shot_spec_v2.yaml").read_text(encoding="utf-8"))["image_compile"]
    assert not A.scan(cfg["fusion_zh"], "reality")[0] and "同一个景深" not in cfg["fusion_zh"]      # 中英同句，英文在括号里
    assert "focal plane" in cfg["fusion_zh"]
    rq = json.loads((ROOT / "config/render_quality.json").read_text(encoding="utf-8"))
    sel = [p for p in rq["image_presets"] if p.get("run") == "series10_v2" and p.get("selected")]
    assert len(sel) == 2
    for p in sel:
        suf = p["params"]["style_suffix"]
        assert not A.scan(suf, "reality")[0] and "Leica" in suf and "Kodak 2383" in suf
        assert "徕卡" not in suf and "50mm f/2" not in suf        # preflight I7 禁 V1 词


def test_ep01_audit_with_merged_scene_table(tmp_path):
    """以现行导入稿为底合并 psm5 → 逐镜 build_first 禁用句 0、L1 句每镜 >=1"""
    sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "packages/schema"), str(ROOT / "services/agent")]
    import import_script as IS
    r = IS.merge_into(ROOT / "data/import/runs/series10_v2/script_v2.json",
                      IS.import_script(ROOT / "data/pipeline/runs/series10_v2/staging/P4_ep01.L1_psm5.md", None), single_source=True)
    p = tmp_path / "merged.json"
    p.write_text(r.model_dump_json(), encoding="utf-8")
    res = A.audit("series10_v2", 1, p, preflight=False)
    assert res["n"] >= 14 and res["banned"] == 0 and res["no_l1"] == 0
