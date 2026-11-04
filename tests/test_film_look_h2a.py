"""H2a：胶片后期档（film_look + image_params.post_file 开关）"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
for _p in ("services/render_router", "packages/schema"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from ns_render import film_look as FL  # noqa: E402
from ns_render import image_params as IP  # noqa: E402


def _img(seed=1, size=(96, 64)):
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
    a[:8] = 255
    a[-8:] = 0
    return Image.fromarray(a)


def test_highlight_compressed_and_black_lifted():
    out = np.asarray(FL.grade_image(_img(), {"grain": 0})[0])
    assert out[:8].max() < 255            # 死白被压
    assert out[-8:].mean() > 3            # 黑位抬起（均值；暗部偏青会压低单通道）


def test_deterministic():
    a = np.asarray(FL.grade_image(_img(), {})[0])
    b = np.asarray(FL.grade_image(_img(), {})[0])
    c = np.asarray(FL.grade_image(_img(2), {})[0])
    assert (a == b).all() and a.shape == c.shape


def test_identity_lut_unchanged(tmp_path):
    n = 5
    lines = [f"LUT_3D_SIZE {n}"]
    for b in range(n):
        for g in range(n):
            for r in range(n):
                lines.append(f"{r/(n-1)} {g/(n-1)} {b/(n-1)}")
    cube = tmp_path / "id.cube"
    cube.write_text("\n".join(lines), encoding="utf-8")
    im = _img()
    out, rec = FL.grade_image(im, None, {"apply": True, "strength": 1.0}, cube)
    assert np.abs(np.asarray(out).astype(int) - np.asarray(im).astype(int)).max() <= 1
    assert rec["lut"]["file"] == "id.cube"


def test_real_cube_reads():
    tb, _, _ = FL.read_cube(ROOT / "config/post/luts/v2_reality_c2.cube")
    assert tb.shape == (33, 33, 33, 3)


def test_post_file_off_is_byte_identical(tmp_path):
    src = tmp_path / "x_raw.png"
    _img(size=(120, 80)).save(src)
    eff = {"tier": "preview", "render_scale": 1.5, "width": 80, "height": 54,
           "sharpen": {"enabled": True, "radius": 1.2, "amount": 0.6, "threshold": 2}}
    r1 = IP.post_file(src, eff, film_cfg={"enabled": False})
    b1 = Path(r1["path"]).read_bytes()
    from PIL import ImageFilter
    im = Image.open(src).convert("RGB").resize((80, 54), Image.LANCZOS).filter(
        ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    ref = tmp_path / "ref.png"
    im.save(ref)
    assert b1 == ref.read_bytes() and "film" not in r1


def test_post_file_on(tmp_path):
    src = tmp_path / "x_raw.png"
    _img(size=(120, 80)).save(src)
    eff = {"tier": "preview", "render_scale": 1.5, "width": 80, "height": 54,
           "sharpen": {"enabled": True, "radius": 1.2, "amount": 0.6, "threshold": 2}}
    cfg = {"enabled": True, "usm": False, "film": {}, "lut": {"apply": False}}
    r = IP.post_file(src, eff, film_cfg=cfg, dst=tmp_path / "x_raw_film.png")
    assert r["unsharp"] is None and r["film"]["version"] == FL.VERSION and r["size"] == [80, 54]
    assert (tmp_path / "x_raw_film.png").exists() and not (tmp_path / "x_raw_post.png").exists()


def test_config_l188_production_on():
    """L-188（项目方“用 L1”）：生产配置 post_film.enabled=true、usm=false、LUT 不叠；生产出图链（film_cfg=None 读配置）走胶片、不做 USM"""
    c = IP.quality()["post_film"]
    assert c["enabled"] is True and c["usm"] is False and c["lut"]["apply"] is False
    assert IP.post_film_cfg() is not None


def test_post_file_reads_config_and_uses_film(tmp_path):
    src = tmp_path / "x_raw.png"
    _img(size=(120, 80)).save(src)
    eff = {"tier": "preview", "render_scale": 1.5, "width": 80, "height": 54,
           "sharpen": {"enabled": True, "radius": 1.2, "amount": 0.6, "threshold": 2}}
    r = IP.post_file(src, eff)            # 不传 film_cfg：生产链读 render_quality.json
    assert r["film"]["version"] == FL.VERSION and r["unsharp"] is None
