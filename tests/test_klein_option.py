"""封板修复：资产生成的 Klein 还没有工作流（笔记本 / gpu3 都没有 Klein 模型），API 返回 501。
界面上的 Klein 选项必须置灰，否则用户选了只会得到 501；接入 Klein 时两处一起改。

UIRSI 重构（2026-10-31）：原来唯一有 Klein 选项的旧资产库组件 components/assets/parts.tsx 已归档到
data/_archive/20261031/code/apps_web/（单一外壳后构建不到）。现在改为扫整个 apps/web/src：
任何地方出现 Klein 选项都必须置灰；没有任何 Klein 选项（选不到）也满足要求。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_klein_option_disabled_while_api_returns_501():
    api = (ROOT / "services" / "api" / "ns_api" / "assets.py").read_text(encoding="utf-8")
    if not re.search(r'req\.model == "klein":\s*\n\s*raise HTTPException\(501', api):
        return
    for f in (ROOT / "apps" / "web" / "src").rglob("*.tsx"):
        for opt in re.finditer(r'<option value="klein"[^>]*>', f.read_text(encoding="utf-8")):
            assert "disabled" in opt.group(0), f"{f}：Klein 选项没有置灰（API 仍返回 501）"
