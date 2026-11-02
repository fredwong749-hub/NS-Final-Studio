"""V2（L-126）：导入器 / validate_qwen_script / storyline schema 放行 lead_* 角色 id（CONSENT 总调度 19:2x）；其他不合法 id 仍拒。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "packages" / "schema", ROOT / "services" / "agent"):
    sys.path.insert(0, str(p))


def test_importer_regex():
    from ns_agent.importer.script_md import CHARACTER_ID_RE as R
    assert R.match("lead_f") and R.match("ch_lu_yu")
    assert not R.match("lead") and not R.match("leadf") and not R.match("su_chi")


def test_schema_regex():
    from ns_schema.upstream_common import CHAR_ID_RE as R
    assert R.match("lead_f") and R.match("ch_ke_yan") and not R.match("su_chi")
