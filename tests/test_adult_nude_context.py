import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "agent"))
import pytest
from ns_agent import compiler as C


@pytest.mark.parametrize("t", ["裸妆、水光粉唇", "短款裸粉美甲", "裸色丝袜", "裸感唇釉", "裸粉色外套", "裸色西装"])
def test_benign_nude_not_adult(t):
    assert not C._keyword_hit("裸", t)


@pytest.mark.parametrize("t", ["裸体", "裸露", "全裸", "半裸", "赤裸", "裸身", "裸背", "她裸着站着", "裸妆但全裸"])
def test_real_nude_still_adult(t):
    assert C._keyword_hit("裸", t)


def test_other_keywords_unchanged():
    assert C._keyword_hit("乳头", "裸妆乳头") and C._keyword_hit("舔", "舔")
