"""封板修复：资产生成的 Klein 还没有工作流（笔记本 / gpu3 都没有 Klein 模型），API 返回 501。
界面上的 Klein 选项必须置灰，否则用户选了只会得到 501；接入 Klein 时两处一起改。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_klein_option_disabled_while_api_returns_501():
    api = (ROOT / "services" / "api" / "ns_api" / "assets.py").read_text(encoding="utf-8")
    ui = (ROOT / "apps" / "web" / "src" / "components" / "assets" / "parts.tsx").read_text(encoding="utf-8")
    if re.search(r'req\.model == "klein":\s*\n\s*raise HTTPException\(501', api):
        opt = re.search(r'<option value="klein"[^>]*>', ui)
        assert opt and "disabled" in opt.group(0)
