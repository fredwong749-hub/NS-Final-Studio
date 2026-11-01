"""ARCH：写作模型实际加载的系统提示词里包含“系统可实现性规则”附录（带版本号），且原有规则不删改、§12 风格条目没被改。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "recipes"))

from ns_api import script_chat as SC  # noqa: E402

TITLE = "## 附录：系统可实现性规则 v1（2026-10-31，来源 ep02 RSI）"


def test_core_rules_file_is_loaded_and_contains_addendum():
    cfg = SC.load_config()
    assert "config/script_chat_rules.md" in cfg["system_parts"]           # 每次都带（不受附录预算影响）
    system, parts = SC.build_system_prompt(cfg, context=None, appendix_budget=None)
    assert TITLE in system
    assert "rules_addendum_version: sysimpl-v1" in system
    for label in ("**站位**", "**地标**", "**光线**", "**分拍**", "**台词时段**", "**独白时段**", "**下镜**", "**出画**",
                  "**镜型**", "**尾帧曝光**"):
        assert label in system, label
    assert any(p["path"] == "config/script_chat_rules.md" for p in parts)


def test_addendum_keeps_style_rules_untouched():
    text = (ROOT / "config" / "script_chat_rules.md").read_text(encoding="utf-8")
    # §12 原本留给项目方决定；项目方 2026-10-31 原话“改成正常节奏”→ FIX 按 §12 第 1 条改写（见 test_fix_ep02_owner_1031）
    assert "动作量按正常速度在 N 秒内做完，并留出最后约 1 秒仍在进行的动作" in text
    head = text.split(TITLE)[0]
    assert "交稿前在心里过一遍" in head                                   # 附录只追加在末尾


def test_addendum_labels_are_what_parser_reads():
    from ns_recipes.spec_import import KNOWN_EXTRAS, rules_version
    text = (ROOT / "config" / "script_chat_rules.md").read_text(encoding="utf-8").split(TITLE)[1]
    for label in KNOWN_EXTRAS - {"硬切"}:
        assert f"**{label}**" in text, label
    assert rules_version().split("+")[-1] >= "sysimpl-v2"   # 附录逐版追加，当前版本取最后一个


def test_manuscript_rules_version_not_current_config():
    from ns_recipes.spec_import import manuscript_rules_version, stamp
    assert manuscript_rules_version("## ep02《x》\n…") == "unknown"
    assert manuscript_rules_version(stamp("## ep02《x》", "rules_v2+sysimpl-v1")) == "rules_v2+sysimpl-v1"
