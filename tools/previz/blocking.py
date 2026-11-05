"""Previz blocking renderer (L-192 ②): 每镜 JSON → 深度图 + OpenPose 骨架图 + 预览图。确定性、纯 numpy 光线投射。

用法：python tools/previz/blocking.py data/previz/ep01-S4/V1_ots.json [--out DIR] [--scale 1.0]
JSON：
  size [W,H]（默认 1152×2016）；camera {pos, look_at, focal_mm, sensor [24,36]（竖拍，全画幅 24×36，裁成 9:16 → 有效宽 20.25）}
  actors [{id, height, pos[x,y,0], face_to[x,y]|yaw_deg, pose: standing|seated|leaning, seat_h, hair: long|bob,
           wrists{left,right:[x,y,z]}（世界坐标，两段 IK），lean_deg}]
  props [{type: box|sphere|cylinder|ring|stand|fan|cyc, ...}]
坐标：x 右、y 前、z 上（米）。角色局部：前=+y，右=+x，yaw=0 面向 +y。
输出：<name>_depth.png（近亮远暗，逆深度）、<name>_pose.png（OpenPose 18 点色）、<name>_preview.png（着色预览）、<name>_ids.png
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

INF = 1e9
# OpenPose body-18 连线与颜色（ControlNet openpose 标准）
LIMBS = [(1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13), (1, 0),
         (0, 14), (14, 16), (0, 15), (15, 17)]
COLORS = [(255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0), (0, 255, 0), (0, 255, 85),
          (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255), (170, 0, 255), (255, 0, 255),
          (255, 0, 170), (255, 0, 85)]


def _n(v):
    v = np.asarray(v, float)
    return v / (np.linalg.norm(v) + 1e-12)


# ---------------------------------------------------------------- 基本体（对一批射线求最近 t）
class Prim:
    def __init__(self, kind, oid, **kw):
        self.kind, self.oid, self.kw = kind, oid, {k: (np.asarray(v, float) if isinstance(v, (list, tuple)) else v) for k, v in kw.items()}

    def hit(self, o, d):
        """o:(3,) 射线原点；d:(N,3) 方向（单位）→ t:(N,)，无命中 INF"""
        k = self.kw
        if self.kind == "sphere":
            return _sphere(o, d, k["c"], k["r"])
        if self.kind == "capsule":
            return _capsule(o, d, k["a"], k["b"], k["r"])
        if self.kind == "box":
            return _obox(o, d, k["c"], k["half"], k["yaw"])
        if self.kind == "plane":
            n, p = k["n"], k["p"]
            den = d @ n
            with np.errstate(divide="ignore", invalid="ignore"):
                t = ((p - o) @ n) / den
            return np.where((den < -1e-9) & (t > 0), t, INF)
        raise ValueError(self.kind)


def _sphere(o, d, c, r):
    oc = o - c
    b = d @ oc
    cc = oc @ oc - r * r
    disc = b * b - cc
    ok = disc > 0
    t = -b - np.sqrt(np.where(ok, disc, 0))
    return np.where(ok & (t > 1e-4), t, INF)


def _capsule(o, d, a, b, r):
    ba = b - a
    L2 = ba @ ba
    if L2 < 1e-12:
        return _sphere(o, d, a, r)
    oa = o - a
    bad = d @ ba
    baoa = ba @ oa
    A = L2 - bad * bad
    B = L2 * (d @ oa) - baoa * bad
    C = L2 * (oa @ oa) - baoa * baoa - r * r * L2
    disc = B * B - A * C
    ok = (disc > 0) & (np.abs(A) > 1e-12)
    t = (-B - np.sqrt(np.where(ok, disc, 0))) / np.where(np.abs(A) > 1e-12, A, 1)
    y = baoa + t * bad
    body = ok & (t > 1e-4) & (y > 0) & (y < L2)
    res = np.where(body, t, INF)
    res = np.minimum(res, _sphere(o, d, a, r))
    res = np.minimum(res, _sphere(o, d, b, r))
    return res


def _obox(o, d, c, half, yaw):
    cy, sy = math.cos(-yaw), math.sin(-yaw)
    R = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    ol = R @ (o - c)
    dl = d @ R.T
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = 1.0 / np.where(np.abs(dl) < 1e-12, 1e-12, dl)
    t1 = (-half - ol) * inv
    t2 = (half - ol) * inv
    tn = np.minimum(t1, t2).max(axis=1)
    tf = np.maximum(t1, t2).min(axis=1)
    return np.where((tn < tf) & (tf > 1e-4) & (tn > 1e-4), tn, INF)


def _cove(o, d, y0, R, zmax=6.0, mirror=False):
    """摄影棚白幕：地面 z=0（y<y0）→ 四分之一圆弧（轴沿 x，圆心 (y0, R)）→ 墙 y=y0+R。返回 t"""
    if mirror:      # 白幕在 -y 侧：整体镜像 y
        o = o * np.array([1, -1, 1])
        d = d * np.array([1, -1, 1])
    t = np.full(len(d), INF)
    # 地面
    with np.errstate(divide="ignore", invalid="ignore"):
        tf = -o[2] / d[:, 2]
    yf = o[1] + tf * d[:, 1]
    m = (d[:, 2] < -1e-9) & (tf > 0) & (yf <= y0)
    t = np.where(m, tf, t)
    # 墙
    with np.errstate(divide="ignore", invalid="ignore"):
        tw = (y0 + R - o[1]) / d[:, 1]
    zw = o[2] + tw * d[:, 2]
    m = (d[:, 1] > 1e-9) & (tw > 0) & (zw >= R) & (zw <= zmax)
    t = np.minimum(t, np.where(m, tw, INF))
    # 圆弧（圆柱内表面，从内侧击中）
    oy, oz = o[1] - y0, o[2] - R
    dy, dz = d[:, 1], d[:, 2]
    A = dy * dy + dz * dz
    B = oy * dy + oz * dz
    C = oy * oy + oz * oz - R * R
    disc = B * B - A * C
    ok = disc > 0
    tc = (-B + np.sqrt(np.where(ok, disc, 0))) / np.where(A > 1e-12, A, 1)   # 远交点（相机在圆外或内）
    yy = oy + tc * dy
    zz = oz + tc * dz
    m = ok & (tc > 1e-4) & (yy >= 0) & (zz <= 0)
    return np.minimum(t, np.where(m, tc, INF))


# ---------------------------------------------------------------- 人偶
def _ik2(sh, target, l1, l2, pole):
    v = target - sh
    dist = min(np.linalg.norm(v), (l1 + l2) * 0.999)
    u = _n(v)
    tgt = sh + u * dist
    a = (l1 * l1 - l2 * l2 + dist * dist) / (2 * dist + 1e-9)
    h = math.sqrt(max(l1 * l1 - a * a, 0))
    pp = _n(np.asarray(pole, float) - u * (np.asarray(pole, float) @ u))
    return sh + u * a + pp * h, tgt


def build_actor(a: dict):
    H = a["height"]
    x0, y0 = a["pos"][0], a["pos"][1]
    if "face_to" in a:
        yaw = math.atan2(-(a["face_to"][0] - x0), a["face_to"][1] - y0)   # yaw 逆时针，0 面向 +y
    else:
        yaw = math.radians(a.get("yaw_deg", 0.0))
    cy, sy = math.cos(yaw), math.sin(yaw)
    Rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    pose = a.get("pose", "standing")
    lean = math.radians(a.get("lean_deg", 0.0))
    s = H / 1.70
    sh_w, hip_w = 0.19 * s, 0.095 * s
    J = {}
    # 局部：x 右，y 前，z 上；站姿
    if pose == "seated":
        seat = a.get("seat_h", 0.46)
        hip_z = seat + 0.08 * s
        hip_c = np.array([0, 0, hip_z])
        torso = 0.50 * s
        up = np.array([0, math.sin(lean), math.cos(lean)])
        neck_c = hip_c + up * torso
        for sd, sg in (("r", 1), ("l", -1)):
            hip = hip_c + [sg * hip_w, 0, 0]
            knee = hip + [sg * 0.02, 0.42 * s, 0.0]
            ankle = knee + [0, 0.05 * s, -(knee[2] - 0.07)]
            J[sd + "hip"], J[sd + "knee"], J[sd + "ankle"] = hip, knee, ankle
    else:
        hip_z = 0.52 * H
        hip_c = np.array([0, 0, hip_z])
        torso = 0.31 * H
        up = np.array([0, math.sin(lean), math.cos(lean)])
        neck_c = hip_c + up * torso
        for sd, sg in (("r", 1), ("l", -1)):
            hip = hip_c + [sg * hip_w, 0, 0]
            knee = hip + [sg * 0.01, 0.01, -0.26 * H]
            ankle = knee + [0, 0, -(knee[2] - 0.06)]
            J[sd + "hip"], J[sd + "knee"], J[sd + "ankle"] = hip, knee, ankle
    fwd = np.array([0, math.cos(lean), -math.sin(lean)])
    J["neck"] = neck_c
    J["rsh"], J["lsh"] = neck_c + [sh_w, 0, -0.03], neck_c + [-sh_w, 0, -0.03]
    head_c = neck_c + up * 0.12 * s + fwd * 0.01
    J["head"] = head_c
    J["nose"] = head_c + fwd * 0.10 * s - [0, 0, 0.01]
    J["reye"], J["leye"] = head_c + fwd * 0.085 * s + [0.035, 0, 0.025], head_c + fwd * 0.085 * s + [-0.035, 0, 0.025]
    J["rear"], J["lear"] = head_c + [0.085 * s, -0.01, 0.0], head_c + [-0.085 * s, -0.01, 0.0]
    l1, l2 = 0.29 * s, 0.27 * s
    wr = a.get("wrists", {})
    for sd, sg in (("r", 1), ("l", -1)):
        sh = J[sd + "sh"]
        if sd in wr:
            tgt_world = np.asarray(wr[sd], float)
            tgt = Rz.T @ (tgt_world - np.array([x0, y0, 0.0]))
        else:
            tgt = sh + [sg * 0.05, 0.02, -(l1 + l2) * 0.97]
            if pose == "seated":
                tgt = sh + [sg * 0.04, 0.30 * s, -0.40 * s]
        el, w = _ik2(sh, tgt, l1, l2, [sg * 0.25, -0.6, -0.8])
        J[sd + "elb"], J[sd + "wri"] = el, w
    # 到世界
    W = {k: Rz @ v + np.array([x0, y0, 0.0]) for k, v in J.items()}
    prims = []
    oid = a["_oid"]
    P = lambda kind, **kw: prims.append(Prim(kind, oid, **kw))   # noqa: E731
    cap = lambda p, q, r: P("capsule", a=W[p], b=W[q], r=r * s)   # noqa: E731
    P("sphere", c=W["head"], r=0.095 * s)
    cap("neck", "head", 0.048)
    cap("rsh", "lsh", 0.045)
    mid_hip = (W["rhip"] + W["lhip"]) / 2
    chest = (W["rsh"] + W["lsh"]) / 2 - np.array([0, 0, 0.12 * s])
    waist = mid_hip + (W["neck"] - mid_hip) * 0.55
    P("capsule", a=chest, b=waist, r=0.125 * s)
    P("capsule", a=waist, b=mid_hip, r=0.125 * s * a.get("waist_k", 1.0))
    P("capsule", a=W["rhip"], b=W["lhip"], r=0.10 * s)
    for sd in "rl":
        cap(sd + "sh", sd + "elb", 0.045)
        cap(sd + "elb", sd + "wri", 0.036)
        P("sphere", c=W[sd + "wri"] + _n(W[sd + "wri"] - W[sd + "elb"]) * 0.05 * s, r=0.04 * s)   # 手
        cap(sd + "hip", sd + "knee", 0.075)
        cap(sd + "knee", sd + "ankle", 0.055)
        P("capsule", a=W[sd + "ankle"], b=W[sd + "ankle"] + Rz @ np.array([0, 0.18 * s, 0]) - np.array([0, 0, 0.0]), r=0.04 * s)
    hair = a.get("hair")
    if hair == "long":    # 披在肩后的长发：两条胶囊从头后垂到腰
        for sg in (1, -1):
            top = W["head"] + Rz @ np.array([sg * 0.05 * s, -0.06 * s, 0.0])
            bot = W["neck"] + Rz @ np.array([sg * 0.12 * s, -0.10 * s, -0.40 * s])
            P("capsule", a=top, b=bot, r=0.055 * s)
        P("sphere", c=W["head"] + Rz @ np.array([0, -0.025 * s, 0.01 * s]), r=0.105 * s)
    elif hair == "bob":
        P("sphere", c=W["head"] + Rz @ np.array([0, -0.02 * s, 0.0]), r=0.11 * s)
        for sg in (1, -1):
            P("capsule", a=W["head"] + Rz @ np.array([sg * 0.08 * s, -0.02 * s, -0.02 * s]),
              b=W["neck"] + Rz @ np.array([sg * 0.10 * s, -0.02 * s, 0.0]), r=0.05 * s)
    return prims, W


# ---------------------------------------------------------------- 道具
def build_prop(p: dict, oid: int):
    t = p["type"]
    out = []
    if t == "box":
        out.append(Prim("box", oid, c=p["pos"], half=np.asarray(p["size"], float) / 2, yaw=math.radians(p.get("yaw_deg", 0))))
    elif t == "sphere":
        out.append(Prim("sphere", oid, c=p["pos"], r=p["r"]))
    elif t == "cylinder":
        x, y, z = p["pos"]
        out.append(Prim("capsule", oid, a=[x, y, z - p["h"] / 2 + p["r"]], b=[x, y, z + p["h"] / 2 - p["r"]], r=p["r"]))
    elif t == "ring":    # 环形灯：竖直圆环（法线沿 normal_yaw 方向）
        x, y, z = p["pos"]
        R, r, nseg = p.get("R", 0.25), p.get("r", 0.022), 28
        ny = math.radians(p.get("normal_yaw_deg", 0))
        nx_, ny_ = -math.sin(ny), math.cos(ny)       # 法线水平方向
        ex, ey = ny_, -nx_                            # 圆环水平轴
        for i in range(nseg):
            a0, a1 = 2 * math.pi * i / nseg, 2 * math.pi * (i + 1) / nseg
            f = lambda a: [x + R * math.cos(a) * ex, y + R * math.cos(a) * ey, z + R * math.sin(a)]   # noqa: E731
            out.append(Prim("capsule", oid, a=f(a0), b=f(a1), r=r))
    elif t == "rod":      # 软尺段 / 细杆：两点胶囊
        out.append(Prim("capsule", oid, a=p["a"], b=p["b"], r=p.get("r", 0.01)))
    elif t == "hring":    # 水平圆环（软尺绕腰）
        x, y, z = p["pos"]
        R, r, nseg = p.get("R", 0.14), p.get("r", 0.009), 36
        f = lambda a: [x + R * math.cos(a), y + R * p.get("ky", 1.0) * math.sin(a), z]   # noqa: E731
        for i in range(nseg):
            out.append(Prim("capsule", oid, a=f(2 * math.pi * i / nseg), b=f(2 * math.pi * (i + 1) / nseg), r=r))
    elif t == "stand":    # 灯架：竖杆 + 三脚
        x, y, z = p["pos"]
        h = p.get("h", 1.8)
        out.append(Prim("capsule", oid, a=[x, y, 0.05], b=[x, y, h], r=p.get("r", 0.018)))
        for k in range(3):
            a = 2 * math.pi * k / 3 + 0.5
            out.append(Prim("capsule", oid, a=[x, y, 0.35], b=[x + 0.35 * math.cos(a), y + 0.35 * math.sin(a), 0.02], r=0.014))
        if "head" in p:   # 灯头：箱形柔光箱
            hs = p["head"]
            out.append(Prim("box", oid, c=[x, y, h + hs[2] / 2 - 0.05], half=np.asarray(hs, float) / 2, yaw=math.radians(p.get("yaw_deg", 0))))
    elif t == "fan":      # 落地风机：底座 + 立杆 + 网罩圆盘
        x, y, z = p["pos"]
        hz = p.get("head_z", 1.0)
        out.append(Prim("capsule", oid, a=[x, y, 0.05], b=[x, y, hz - 0.2], r=0.03))
        out.append(Prim("capsule", oid, a=[x, y, 0.03], b=[x, y, 0.06], r=0.18))
        out.append(Prim("capsule", oid, a=[x, y - 0.05 * p.get("fy", -1), hz], b=[x, y + 0.05 * p.get("fy", -1), hz], r=0.21))
    elif t == "cyc":      # 白幕
        out.append(("cyc", oid, p))
    else:
        raise ValueError(t)
    return out


# ---------------------------------------------------------------- 相机
def make_rays(cam, W, H):
    pos = np.asarray(cam["pos"], float)
    fwd = _n(np.asarray(cam["look_at"], float) - pos)
    right = _n(np.cross(fwd, [0, 0, 1]))
    up = np.cross(right, fwd)
    sw, sh = cam.get("sensor", [24.0, 36.0])
    # 竖拍裁成 9:16：保持传感器高度，宽度按画幅比
    eff_w = sh * W / H
    f = cam["focal_mm"]
    u = ((np.arange(W) + 0.5) / W - 0.5) * eff_w / f
    v = (0.5 - (np.arange(H) + 0.5) / H) * sh / f
    return pos, fwd, right, up, u, v, f, eff_w, sh


def render(spec: dict, scale: float = 1.0):
    W, H = spec.get("size", [1152, 2016])
    W, H = int(W * scale), int(H * scale)
    cam = spec["camera"]
    pos, fwd, right, up, u, v, f, eff_w, sh = make_rays(cam, W, H)
    prims, joints, cyc = [], {}, []
    oid = 1
    names = {0: "bg"}
    for a in spec.get("actors", []):
        a = dict(a)
        a["_oid"] = oid
        pr, Wd = build_actor(a)
        prims += pr
        joints[a["id"]] = Wd
        names[oid] = a["id"]
        oid += 1
    for p in spec.get("props", []):
        for e in build_prop(p, oid):
            (cyc if isinstance(e, tuple) else prims).append(e)
        names[oid] = p.get("name", p["type"])
        oid += 1
    depth = np.full((H, W), np.inf, np.float32)
    ids = np.zeros((H, W), np.uint8)
    cosz = np.zeros((H, W), np.float32)
    rows = max(1, int(250000 // W))
    for r0 in range(0, H, rows):
        r1 = min(H, r0 + rows)
        uu, vv = np.meshgrid(u, v[r0:r1])
        d = fwd[None, None] + uu[..., None] * right + vv[..., None] * up
        nrm = np.linalg.norm(d, axis=-1)
        d = (d / nrm[..., None]).reshape(-1, 3)
        best = np.full(len(d), INF)
        bid = np.zeros(len(d), np.uint8)
        for pr in prims:
            t = pr.hit(pos, d)
            m = t < best
            best = np.where(m, t, best)
            bid = np.where(m, pr.oid, bid)
        for (_, o_, p) in cyc:
            t = _cove(pos, d, p.get("y0", 4.0), p.get("R", 0.9), mirror=p.get("mirror", False))
            m = t < best
            best = np.where(m, t, best)
            bid = np.where(m, o_, bid)
        # 以相机前向轴上的深度（z-depth）为准
        zd = best * (d @ fwd)
        depth[r0:r1] = np.where(best < INF, zd, np.inf).reshape(r1 - r0, W)
        ids[r0:r1] = bid.reshape(r1 - r0, W)
    return depth, ids, joints, names, (W, H, f, eff_w, sh, pos, fwd, right, up)


def depth_to_img(depth, near=None, far=None):
    d = depth.copy()
    fin = np.isfinite(d)
    d[~fin] = (np.nanmax(d[fin]) if fin.any() else 10)
    near = near or float(d.min())
    far = far or float(d.max())
    disp = (1 / np.maximum(d, 1e-3) - 1 / far) / (1 / near - 1 / far + 1e-9)    # 近=1
    disp = np.clip(disp, 0, 1) ** 0.8
    return (disp * 255).astype(np.uint8)


def project(Pw, cam_info):
    W, H, f, eff_w, sh, pos, fwd, right, up = cam_info
    v = np.asarray(Pw) - pos
    z = v @ fwd
    if z <= 0.05:
        return None
    x = (v @ right) / z * f / eff_w * W + W / 2
    y = H / 2 - (v @ up) / z * f / sh * H
    return x, y


def pose_img(joints, cam_info, width_px=None):
    W, H = cam_info[0], cam_info[1]
    img = Image.new("RGB", (W, H))
    dr = ImageDraw.Draw(img)
    lw = width_px or max(4, int(W / 100))
    order = ["nose", "neck", "rsh", "relb", "rwri", "lsh", "lelb", "lwri", "rhip", "rknee", "rankle", "lhip", "lknee", "lankle",
             "reye", "leye", "rear", "lear"]
    for J in joints.values():
        pts = [project(J[n], cam_info) for n in order]
        for i, (a, b) in enumerate(LIMBS):
            if pts[a] and pts[b]:
                dr.line([pts[a], pts[b]], fill=COLORS[i], width=lw)
        for i, p in enumerate(pts):
            if p:
                dr.ellipse([p[0] - lw, p[1] - lw, p[0] + lw, p[1] + lw], fill=COLORS[i])
    return img


PALETTE = {0: (30, 30, 36), 1: (150, 40, 60), 2: (70, 110, 200)}


def preview_img(depth, ids, names):
    H, W = depth.shape
    d = np.where(np.isfinite(depth), depth, np.nanmax(depth[np.isfinite(depth)]))
    gy, gx = np.gradient(d)
    shade = np.clip(0.75 - 3.0 * (gx + gy), 0.25, 1.0)
    rng = np.random.RandomState(7)
    pal = {k: PALETTE.get(k) or tuple(int(x) for x in rng.randint(90, 230, 3)) for k in names}
    pal[0] = (214, 214, 220)
    rgb = np.zeros((H, W, 3), np.float32)
    for k, c in pal.items():
        rgb[ids == k] = c
    fade = np.clip(1.15 - d / 12.0, 0.55, 1.0)
    return Image.fromarray(np.clip(rgb * shade[..., None] * fade[..., None], 0, 255).astype(np.uint8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--out", default=None)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--no-pose", action="store_true")
    a = ap.parse_args()
    sp = Path(a.spec)
    spec = json.loads(sp.read_text(encoding="utf-8"))
    out = Path(a.out) if a.out else sp.parent / "out"
    out.mkdir(parents=True, exist_ok=True)
    depth, ids, joints, names, ci = render(spec, a.scale)
    stem = sp.stem
    Image.fromarray(depth_to_img(depth, spec.get("depth_near"), spec.get("depth_far"))).save(out / f"{stem}_depth.png")
    Image.fromarray(ids).save(out / f"{stem}_ids.png")
    preview_img(depth, ids, names).save(out / f"{stem}_preview.png")
    if not a.no_pose:
        pose_img(joints, ci).save(out / f"{stem}_pose.png")
    print("ok", out / f"{stem}_depth.png")


if __name__ == "__main__":
    main()
