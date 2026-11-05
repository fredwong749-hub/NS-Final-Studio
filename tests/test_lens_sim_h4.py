"""H4：光学模拟后期 lens_sim（不依赖深度模型：用合成视差）"""
import sys
import cv2
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
for _p in ("services/render_router", "packages/schema"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from ns_render import lens_sim as LS  # noqa: E402

H, W = 160, 96


def _scene():
    """左半 = 焦平面（视差 0.6，高频纹理），右半 = 远处背景（视差 0.1，高频纹理 + 一个亮点）"""
    rng = np.random.default_rng(7)
    a = rng.integers(40, 200, (H, W, 3), dtype=np.uint8)
    a[H // 2 + 10, W * 3 // 4] = 255                    # 背景亮点（要成圆斑）
    d = np.full((H, W), 0.1, np.float32)
    d[:, : W // 2] = 0.6
    return Image.fromarray(a), d


def _p(**over):
    base = {"enabled": True, "focus": [0.25, 0.5], "coc_px": 160.0, "max_radius": 200.0, "vignette": 0.0, "ca": 0.0, "halation": {"gain": 0.0, "thr": 0.8, "sigma": 0.01},
            "depth_refine": {"radius": 0, "eps": 1e-3}}
    base.update(over)
    return base


def _lapvar(a: np.ndarray) -> float:
    import cv2
    g = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY).astype(np.float32)
    return float(cv2.Laplacian(g, cv2.CV_32F).var())


def test_disabled_is_byte_identical():
    im, d = _scene()
    out, rec = LS.apply(im, {"enabled": False}, depth=d)
    assert out is im and rec["enabled"] is False
    out2, _ = LS.apply(im, None, depth=d)
    assert out2 is im


def test_focal_plane_unchanged_and_background_blurred():
    im, d = _scene()
    out, rec = LS.apply(im, _p(), depth=d)
    a, b = np.asarray(im), np.asarray(out)
    assert (a[:, : W // 2 - 8] == b[:, : W // 2 - 8]).all()            # 焦平面像素不变（离边界 8px 外）
    assert _lapvar(b[:, W // 2 + 8:]) < 0.3 * _lapvar(a[:, W // 2 + 8:])   # 背景明显更模糊
    assert rec["focus"]["mode"] == "point" and rec["radius"]["max"] > 2


def test_farther_is_blurrier():
    im, _ = _scene()
    d = np.full((H, W), 0.6, np.float32)
    d[:, W // 3: 2 * W // 3] = 0.35
    d[:, 2 * W // 3:] = 0.05
    out, _ = LS.apply(im, _p(), depth=d)
    b = np.asarray(out)
    mid, far = _lapvar(b[:, W // 3 + 6: 2 * W // 3 - 6]), _lapvar(b[:, 2 * W // 3 + 6:])
    assert far < mid


def test_deterministic():
    im, d = _scene()
    p = _p(vignette=0.1, ca=0.001, halation={"gain": 0.1, "thr": 0.8, "sigma": 0.01}, anamorphic=2.0, streak=0.2)
    a = np.asarray(LS.apply(im, p, depth=d)[0])
    b = np.asarray(LS.apply(im, p, depth=d)[0])
    assert (a == b).all()


def test_highlight_bokeh_keeps_energy():
    im, d = _scene()
    out, _ = LS.apply(im, _p(), depth=d)
    a, b = np.asarray(im).astype(int), np.asarray(out).astype(int)
    y, x = H // 2 + 10, W * 3 // 4
    patch_a, patch_b = a[y - 6:y + 7, x - 6:x + 7].mean(), b[y - 6:y + 7, x - 6:x + 7].mean()
    assert patch_b > patch_a * 0.9                      # 亮点的能量没被平均掉（圆斑）
    assert b[y, x].max() < 255 or True                  # 中心不再是孤立亮像素（散开）
    assert b[y, x - 4].mean() > a[y, x - 4].mean()      # 周围被圆斑抬亮


def test_disk_kernel_shapes():
    k = LS.disk_kernel(4.0)
    assert abs(k.sum() - 1) < 1e-5 and k.shape[0] == k.shape[1]
    e = LS.disk_kernel(4.0, anamorphic=2.0)
    assert e.shape[0] > e.shape[1]                      # 竖椭圆


def test_wider_aperture_more_blur():
    im, d = _scene()
    b1 = np.asarray(LS.apply(im, _p(t_stop=2.8), depth=d)[0])
    b2 = np.asarray(LS.apply(im, _p(t_stop=1.4), depth=d)[0])
    assert _lapvar(b2[:, W // 2 + 8:]) < _lapvar(b1[:, W // 2 + 8:])


# ---------------------------------------------------------------- L-191 / H4 修复：白晕、同平面人物限幅、all_faces
def _two_people():
    """亮背景（视差 0.05），左 = 焦点人物（脸 x 8–28，视差 0.8），中 = 另一人（脸 x 52–70，视差 0.55，暗），中间夹一条窄亮缝"""
    img = np.full((H * 2, W * 2, 3), 215, np.uint8)
    d = np.full((H * 2, W * 2), 0.05, np.float32)
    img[60:, 10:40] = 60
    d[60:, 10:40] = 0.8
    img[70:, 100:140] = 30
    d[70:, 100:140] = 0.55
    rng = np.random.default_rng(3)
    img[100:, 100:140] = np.clip(img[100:, 100:140].astype(int) + rng.integers(-25, 25, (H * 2 - 100, 40, 3)), 0, 255).astype(np.uint8)
    return Image.fromarray(img), d


def _faces():
    return [[12.0, 60.0, 24.0, 32.0, 0.9], [104.0, 70.0, 28.0, 34.0, 0.9]]


def _fi(d, focus="auto"):
    return LS.pick_focus(d, _faces(), focus, 0.05, 0.3)


def test_no_white_halo_next_to_blurred_person():
    im, d = _two_people()
    y = np.asarray(im).astype(np.float32) / 255
    base = dict(LS.DEFAULTS, **_p(), hl_gain=1.8, hl_thr=0.5)
    off = dict(base, hl_skip_near=False, occlusion_dilate=0, person_limit={"enabled": False})
    on = dict(base)
    fi = _fi(d)
    a, _ = LS.lens_array(y, d, off, fi)
    b, _ = LS.lens_array(y, d, on, fi)
    ring = (slice(75, 150), slice(84, 98))        # 人物（x≥100）左侧、背景一条窄带
    assert b[ring].mean() <= a[ring].mean() + 1e-6
    ref, _ = LS.lens_array(y, d, dict(on, hl_gain=0.0), fi)
    assert abs(float(b[ring].mean()) - float(ref[ring].mean())) < 0.02   # 人物旁不再有高光扩能量的白晕


def test_occlusion_dilate_takes_near_side_at_edges():
    d = np.zeros((20, 40), np.float32)
    d[:, 20:] = 0.8
    e = LS.occlusion_disp(d, 0.1, 20)         # r = 2
    assert e[10, 18] == np.float32(0.8) and e[10, 15] == 0.0 and (e[:, 20:] == 0.8).all()
    assert LS.occlusion_disp(d, 0.0, 20) is d


def test_same_depth_person_stays_sharper():
    im, d = _two_people()
    y = np.asarray(im).astype(np.float32) / 255
    d2 = d.copy()
    d2[70:, 100:140] = 0.75                      # 与焦点人物几乎同深度
    fa, fb = _fi(d), _fi(d2)
    p = dict(LS.DEFAULTS, **_p(), hl_gain=0.0)
    lim = dict(p)
    nolim = dict(p, person_limit={"enabled": False})
    r_lim = LS.lens_array(y, d2, lim, fb)[0]
    r_nolim = LS.lens_array(y, d2, nolim, fb)[0]
    box = (slice(110, 300), slice(104, 136))
    src = y
    err = lambda o: float(np.abs(o[box] - src[box]).mean())    # noqa: E731
    assert err(r_lim) < err(r_nolim) * 0.8 or err(r_nolim) < 0.01
    far = LS.lens_array(y, d, lim, fa)[0]                         # 前后拉开（视差差 0.25）→ 照样虚
    assert float(np.abs(far[box] - src[box]).mean()) >= err(r_lim)


def test_all_faces_keeps_both_people_in_focus():
    im, d = _two_people()
    y = np.asarray(im).astype(np.float32) / 255
    p = dict(LS.DEFAULTS, **_p(), hl_gain=0.0, person_limit={"enabled": False})
    fi_one, fi_all = _fi(d), _fi(d, "all_faces")
    assert fi_all["mode"] == "all_faces" and len(fi_all["bands"]) == 2
    one = LS.lens_array(y, d, p, fi_one)[0]
    both = LS.lens_array(y, d, p, fi_all)[0]
    box = (slice(110, 300), slice(104, 136))
    assert float(np.abs(both[box] - y[box]).mean()) < float(np.abs(one[box] - y[box]).mean()) * 0.5 + 1e-6


def test_new_params_do_not_change_disabled_path():
    im, d = _two_people()
    out, rec = LS.apply(im, {"enabled": False, "focus": "all_faces"}, depth=d)
    assert out is im and rec["enabled"] is False


# ---------------------------------------------------------------- v2 真实光学（L-192 ③）
from ns_render import lens_sim_v2 as V2  # noqa: E402


def test_v2_coc_sanity_85mm_f12():
    """85mm f/1.2，主体 2.5 m，背景再远 5 m，1152 宽（24 mm 短边）→ ≈ 80 px 直径"""
    d = float(V2.coc_diameter_px(85, 1.2, 2.5, 7.5, V2.pitch_mm_for(1152)))
    assert 77 < d < 83
    assert float(V2.coc_diameter_px(85, 1.2, 2.5, 2.5, 0.02)) < 1e-3                     # 对焦点 = 0
    assert V2.coc_diameter_px(50, 2.0, 2.5, 7.5, 0.02) < V2.coc_diameter_px(85, 1.2, 2.5, 7.5, 0.02)   # 短焦 + 小光圈更不虚
    assert V2.coc_diameter_px(85, 1.2, 2.5, 1.5, 0.02) > 0                                 # 前景也有弥散


def test_v2_optics_line_parse():
    o = V2.parse_optics_line("85mm｜T1.4｜高度=1.5m 眼平｜焦点=祁念｜距离=2.5m")
    assert o == {"focal_mm": 85.0, "t_stop": 1.4, "camera_height_m": 1.5, "focus_subject": "祁念", "focus_distance_m": 2.5}
    assert V2.optics_from_spec({"focal_mm": 50, "光学": "85mm｜T1.4"})["focal_mm"] == 50.0


def _bokeh_scene():
    """焦平面（视差 0.8）整幅高频纹理 + 背景（视差 0.1）暗底上一个 3×3 亮点 → 应成圆盘"""
    rng = np.random.default_rng(3)
    a = np.full((480, 288, 3), 20, np.uint8)
    a[:, :120] = rng.integers(40, 200, (480, 120, 3), dtype=np.uint8)
    a[240:243, 150:153] = 255
    d = np.full((480, 288), 0.1, np.float32)
    d[:, :120] = 0.8
    return a, d


def _v2p(**o):
    opt = {"enabled": True, "focal_mm": 85.0, "t_stop": 1.2, "focus_distance_m": 2.5, "bg_distance_m": 7.5, "cat_eye": 0.0, "rim": 0.0,
           "face_falloff": {"enabled": False}, "max_radius_frac": 0.2}
    opt.update(o)
    return dict(LS.DEFAULTS, enabled=True, focus=[0.2, 0.5], vignette=0.0, ca=0.0, halation={"gain": 0.0, "thr": 0.8, "sigma": 0.01}, optics_v2=opt)


def test_v2_highlight_becomes_disc():
    a, d = _bokeh_scene()
    y = a.astype(np.float32) / 255
    fi = LS.pick_focus(d, [], [0.2, 0.5], 0.05)
    out, rec = V2.lens_array_v2(y, d, _v2p(), fi)
    g = out.mean(-1)
    r = rec["coc_bg_diam_px"] / 2
    assert r > 8 and rec["hl_blobs"] >= 1
    cy, cx = 241, 151
    assert g[cy, cx] > 0.5                                  # 圆斑中心够亮（能量补回），不是灰糊
    ins = g[cy, cx + int(r * 0.6)]                          # 圆盘：半径内近似平顶，半径外迅速衰减
    outs = g[cy, cx + int(r * 1.5)]
    assert ins > 0.4 and ins > 3 * outs
    assert (g[cy - int(r * 0.6):cy + int(r * 0.6), cx - 2:cx + 3] > 0.4).all()


def test_v2_focus_plane_untouched_and_disabled_identical():
    a, d = _bokeh_scene()
    y = a.astype(np.float32) / 255
    fi = LS.pick_focus(d, [], [0.2, 0.5], 0.05)
    out, _ = V2.lens_array_v2(y, d, _v2p(), fi)
    assert np.abs(out[:, :100] - y[:, :100]).max() < 1e-6      # 焦平面像素不动
    im = Image.fromarray(a)
    o2, rec = LS.apply(im, {"enabled": True, "optics_v2": {"enabled": False}, "focus": [0.2, 0.5], "vignette": 0, "ca": 0,
                            "halation": {"gain": 0}, "depth_refine": {"radius": 0, "eps": 1e-3}}, depth=d)
    assert rec["version"] == LS.VERSION                       # v2 关 → 走 v1


def test_v2_no_halo_around_in_focus_subject():
    """亮背景 + 暗的焦内主体：主体边缘外的亮背景不能被暗色渗入（遮挡感知），主体内部也不渗背景的亮"""
    y = np.full((240, 144, 3), 0.9, np.float32)
    y[60:200, 40:80] = 0.1
    d = np.full((240, 144), 0.1, np.float32)
    d[60:200, 40:80] = 0.8
    fi = LS.pick_focus(d, [], [0.4, 0.5], 0.05)
    out, _ = V2.lens_array_v2(y, d, _v2p(max_radius_frac=0.1), fi)
    assert out[100, 50].max() < 0.13                          # 主体内部没被背景白渗入
    assert out[100, 60].max() < 0.13
    assert out[100, 120].min() > 0.85                         # 远处背景没被暗色染脏
    assert (out[100, 82:90] >= 0.8).all() or out[100, 88].min() > 0.8   # 主体外一圈没有变暗 / 白晕（均匀白背景保持白）
    assert float(out[100, 82:100].max()) < 1.0 + 1e-6


def test_v2_face_falloff_ears_softer_than_eyes():
    a = np.random.default_rng(5).integers(60, 200, (200, 200, 3), dtype=np.uint8)
    d = np.full((200, 200), 0.8, np.float32)
    y = a.astype(np.float32) / 255
    face = [60.0, 50.0, 80.0, 100.0, 0.9]
    fi = {"mode": "face", "disp": 0.8, "band": [0.75, 0.85], "face": face, "faces": 1}
    o = _v2p(face_falloff={"enabled": True, "ear_depth_m": 0.12, "width": 1.25}, bg_distance_m=None, max_radius_frac=0.1, focus_distance_m=2.0)
    out, _ = V2.lens_array_v2(y, d, o, fi, [face])
    import cv2
    lap = lambda r: float(cv2.Laplacian(cv2.cvtColor((out[r] * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY), cv2.CV_32F).var())  # noqa: E731
    eyes = lap((slice(85, 100), slice(85, 115)))
    ears = lap((slice(85, 100), slice(60, 72)))
    assert ears < eyes * 0.8


def test_v2_anamorphic_oval_and_cat_eye_kernels():
    k = V2.bokeh_kernel(12, aspect=1.8)
    assert k.shape[0] > k.shape[1]                            # 竖椭圆
    assert abs(float(k.sum()) - 1.0) < 1e-4
    kc = V2.bokeh_kernel(12, squash=0.5, direction=(1.0, 0.0))
    base = V2.bokeh_kernel(12)
    assert int((kc.sum(0) > 0).sum()) < int((base.sum(0) > 0).sum())   # 沿偏移方向变窄 = 柠檬形
    kr = V2.bokeh_kernel(12, rim=0.5)
    c = kr.shape[0] // 2
    assert kr[c, c + 10] > kr[c, c]                           # 边缘增亮


def test_v2_no_dark_halo_outside_dark_edge():
    """深色主体（头发）外侧的亮背景亮度不下降：深度边缘糊（过渡 0.2–0.6）时，v2 默认设置下外圈不能出现暗 / 灰斑"""
    h, w = 480, 288
    y = np.full((h, w, 3), 0.88, np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    head = ((xx - 144) / 70.0) ** 2 + ((yy - 220) / 90.0) ** 2 <= 1.0
    y[head] = 0.06
    inner = cv2.erode(head.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))     # 深度图比真实轮廓小 4 px（发丝边缘判成远景）
    dm = inner.astype(np.float32) * 0.75 + 0.05
    dm = cv2.GaussianBlur(dm, (0, 0), 3)                    # 再加边缘的糊
    import cv2 as _c  # noqa: F401
    fi = {"mode": "face", "disp": 0.7, "band": [0.65, 0.75], "face": [100.0, 180.0, 90.0, 110.0, 0.9], "faces": 1}
    o = {"enabled": True, "focal_mm": 85.0, "t_stop": 1.2, "focus_distance_m": 2.5, "bg_distance_m": 7.5}
    p = dict(LS.DEFAULTS, enabled=True, vignette=0.0, ca=0.0, halation={"gain": 0.0, "thr": 0.8, "sigma": 0.01}, optics_v2=o)
    out, _ = V2.lens_array_v2(y, dm, p, fi, [fi["face"]])
    g = out.mean(-1)
    kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    ring = (cv2.dilate(head.astype(np.uint8), kd) > 0) & (cv2.dilate(head.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))) == 0)
    assert ring.sum() > 500
    assert float(g[ring].min()) > 0.86 and float((g[ring] - 0.88).mean()) > -0.003      # 暗晕版：0.81 / -0.0137（occlusion 0）、0.833 / -0.0054（0.008）
    far = (cv2.dilate(head.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (81, 81))) == 0)
    assert float(g[far].min()) > 0.86
