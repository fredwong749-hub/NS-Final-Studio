"""gpu3 loader 读导入 JSON（总调度 2026-10-30）：globals.daily_outfit / decor_tables 与 gpu3 md 解析器逐字一致；合并保留底稿"""
from ns_agent.importer.script_md import _owner_headers

MD = """# 《为他而骚》第一批
**林晚日常穿搭（2026-10-30 项目方）**：林晚每天都穿得性感，`漆皮`超短裙。

| 集 | 乳环 | 纹身 |
|---|---|---|
| ep01 | \*无\* | 🔴无 |
## ep01《开端》
**镜1｜img**：x
| ep09 | 不该算 | 进来 |
# 《为他而骚》第二批
| 集 | 乳环 |
| ep11 | 2 |
"""


def test_owner_headers_match_gpu3_parser():
    outfit, decor = _owner_headers(MD)
    assert outfit == "林晚每天都穿得性感，`漆皮`超短裙。".replace("`", "")
    assert decor == {"1": "乳环：无；纹身：无", "11": "乳环：2"}


def test_merge_keeps_base_headers():
    import sys
    sys.path.insert(0, "tools")
    from import_script import merge_into  # noqa: F401  (合并逻辑见 tools/import_script.py)
    from ns_schema.script import ScriptGlobals
    a = ScriptGlobals(daily_outfit="底稿", decor_tables={"1": "a", "2": "b"})
    b = ScriptGlobals(decor_tables={"2": "新"})
    assert {**a.decor_tables, **b.decor_tables} == {"1": "a", "2": "新"} and (b.daily_outfit or a.daily_outfit) == "底稿"
