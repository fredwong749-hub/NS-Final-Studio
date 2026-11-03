"""2.5D 视差子弹时间（实验；STYLE-V2，总调度 20:4x：Pika 只靠提示词做不出“定格 + 环绕”，改用现有定格帧在后期做）。

做法：一张定格帧 → 深度（Depth-Anything-V2-Small，gpu36 CPU，config/v2style.json depth）+ 人物分割（MediaPipe
selfie_multiclass，本机 models_cache/vision）→ 背景按深度做反向视差平移（以人物深度为轴心，近处和远处反向移动 = 机位绕人转），
人物层整体不动（时间定格），只做随角度的轻微水平压缩模拟转体；露出的空洞用背景修补（cv2.inpaint）。纯 CPU，不占 GPU 道。
输出 data/ab/v2_style/camera/parallax_*/：mp4（768×1344，24 fps，4 s）+ 抽帧条；结果并进 camera 的 results.json（move = parallax_bt）。

  python tools/v2style/parallax_bt.py run
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/v2style"))
import common as C  # noqa: E402

OUT = ROOT / "data/ab/v2_style/camera"
RES = OUT / "results.json"
SEG_MODEL = ROOT / "models_cache/vision/selfie_multiclass_256x256.tflite"
FRAMES = {   # 现有定格帧（调色样张调色前的 _post.png；与运镜 A/B 首帧同一批）
    "F_full": "data/ab/v2_style/grade/fantasy_a/s2_post.png",
    "F_mid": "data/ab/v2_style/grade/fantasy_a/s3_post.png",
    "F_close": "data/ab/v2_style/grade/fantasy_a/s1_post.png",
}
VARIANTS = {   # 名: (背景最大视差占画宽, 人物转体压缩, 推近比例, 方向)
    "orbit": (0.07, 0.06, 0.0, 1),
    "orbit_push": (0.10, 0.08, 0.06, -1),
}
FPS, SECS = 24, 4.0
MAX_CLIPS = 6


def depth_maps(names: list[str]) -> dict[str, np.ndarray]:
    """gpu36 CPU 上跑深度；返回 {name: float32 深度（越大越近，0–1）}"""
    cfg = C.cfg()["depth"]
    wd = cfg["work_dir"]
    out = {}
    for n in names:
        cache = OUT / "parallax_depth" / f"{n}.png"
        if cache.exists():
            out[n] = cv2.imread(str(cache), cv2.IMREAD_UNCHANGED).astype(np.float32) / 65535.0
            continue
        C.remote(cfg["host"], f"mkdir -p {wd} && cat > {wd}/{n}.png", stdin=(ROOT / FRAMES[n]).read_bytes(), timeout=600)
        code = ("import sys,numpy as np,torch;from PIL import Image;from transformers import pipeline;"
                f"p=pipeline('depth-estimation',model='{cfg['model_dir']}',device='cpu');"
                f"im=Image.open('{wd}/{n}.png').convert('RGB');d=p(im)['predicted_depth'];"
                "d=torch.nn.functional.interpolate(d[None] if d.dim()==3 else d[None,None],size=im.size[::-1],mode='bicubic')[0,0].numpy();"
                "d=(d-d.min())/(d.max()-d.min()+1e-6);"
                f"Image.fromarray((d*65535).astype(np.uint16)).save('{wd}/{n}_depth.png')")
        r = C.remote(cfg["host"], f"OMP_NUM_THREADS=8 {cfg['python']} -c \"{code}\" 2>&1 | tail -3", timeout=900)
        got = C.remote(cfg["host"], f"cat {wd}/{n}_depth.png", timeout=600)
        if got.returncode or not got.stdout:
            raise RuntimeError(f"深度失败 {n}: {r.stdout.decode('utf-8', 'replace')[-300:]}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(got.stdout)
        out[n] = cv2.imread(str(cache), cv2.IMREAD_UNCHANGED).astype(np.float32) / 65535.0
    return out


def person_mask(img_rgb: np.ndarray) -> np.ndarray:
    import mediapipe as mp
    from mediapipe.tasks.python import vision as V
    from mediapipe.tasks.python.core.base_options import BaseOptions
    opts = V.ImageSegmenterOptions(base_options=BaseOptions(model_asset_path=str(SEG_MODEL)), output_category_mask=True)
    with V.ImageSegmenter.create_from_options(opts) as seg:
        r = seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(img_rgb)))
        cat = r.category_mask.numpy_view()
    m = (cat > 0).astype(np.uint8)          # 0 = 背景；1–5 = 头发 / 身体皮肤 / 脸 / 衣服 / 其他
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    return m


def render(name: str, variant: str, img: np.ndarray, depth: np.ndarray, mask: np.ndarray, dst: Path) -> None:
    h, w = img.shape[:2]
    amp, squeeze, push, sgn = VARIANTS[variant]
    pivot = float(np.median(depth[mask > 0])) if mask.any() else 0.5
    dil = cv2.dilate(mask, np.ones((25, 25), np.uint8))
    bg = cv2.inpaint(img, dil * 255, 9, cv2.INPAINT_TELEA)      # 人物挖掉后修补，给视差露出的空洞
    soft = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 2.0)[..., None]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    cx = float(xs[mask > 0].mean()) if mask.any() else w / 2
    dsm = cv2.GaussianBlur(depth, (0, 0), 6)
    n = int(FPS * SECS)
    tmp = dst.with_suffix(".frames")
    tmp.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        t = i / (n - 1)
        a = sgn * (0.5 - 0.5 * np.cos(np.pi * t) - 0.5) * 2        # −1 → 1，缓入缓出
        dx = (a * amp * w * (pivot - dsm)).astype(np.float32)        # 比人远的往一边、比人近的往另一边
        bgf = cv2.remap(bg, xs - dx, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        sx = 1.0 - squeeze * abs(a)                                 # 人物转体：以人物中心水平轻压
        px = ((xs - cx) / sx + cx).astype(np.float32)
        per = cv2.remap(img, px, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        pm = cv2.remap(soft, px, ys, cv2.INTER_LINEAR)[..., None]
        fr = (per * pm + bgf * (1 - pm)).astype(np.uint8)
        if push:
            z = 1.0 + push * t
            M = cv2.getRotationMatrix2D((cx, h * 0.4), 0, z)
            fr = cv2.warpAffine(fr, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        cv2.imwrite(str(tmp / f"{i:04d}.png"), cv2.cvtColor(fr, cv2.COLOR_RGB2BGR))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(tmp / "%04d.png"), "-c:v", "libx264",
                    "-crf", "16", "-pix_fmt", "yuv420p", str(dst)], check=True, timeout=600)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(dst), "-vf",
                    r"select='eq(n\,0)+eq(n\,19)+eq(n\,38)+eq(n\,57)+eq(n\,76)+eq(n\,95)',scale=216:378,tile=6x1",
                    "-frames:v", "1", str(dst.with_name(dst.stem + "_strip.jpg"))], check=True, timeout=300)


def run() -> None:
    dm = depth_maps(list(FRAMES))
    clips = [(f, v) for f in FRAMES for v in VARIANTS][:MAX_CLIPS]
    for f, v in clips:
        img = cv2.cvtColor(cv2.imread(str(ROOT / FRAMES[f])), cv2.COLOR_BGR2RGB)
        d = cv2.resize(dm[f], (img.shape[1], img.shape[0]))
        m = person_mask(img)
        aid = f"parallax_bt__{f}_{v}"
        dst = OUT / aid / f"{aid}.mp4"
        dst.parent.mkdir(parents=True, exist_ok=True)
        render(f, v, img, d, m, dst)
        rec = {"id": aid, "move": "parallax_bt", "first": f, "variant": v, "seed": None, "experimental": True,
               "first_frame": FRAMES[f], "method": "2.5D 视差：Depth-Anything-V2-Small 深度 + MediaPipe 人物分割 + cv2 重映射 / 修补",
               "params": dict(zip(("bg_parallax_w", "person_squeeze", "push", "dir"), VARIANTS[v])),
               "mp4": dst.relative_to(ROOT).as_posix(), "strip": dst.with_name(dst.stem + "_strip.jpg").relative_to(ROOT).as_posix()}
        with C.file_lock(RES.with_suffix(".lock")):
            res = C.load_json(RES, {})
            res[aid] = rec
            C.save_json_atomic(RES, res)
        print(aid, flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        run()
    else:
        print(__doc__)
