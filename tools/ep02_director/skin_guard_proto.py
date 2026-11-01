"""原型（DIR 2026-10-31，未接入生产链；用法：skin_guard_proto.py in.mp4 out.mp4 [margin=6] [knee=0.25]；已知问题：嘴唇也被压，接入前要排除嘴唇椭圆）：林晚脸部 a* 限幅。脸框（YuNet，360 跟踪→原分辨率）外扩 25 %、羽化；
框内 a* 高于 T = 首帧脸颊 a*p95 + MARGIN 的部分按 KNEE 压缩。只动 a*，L*/b* 不动。"""
import sys, subprocess
from pathlib import Path
import numpy as np, cv2
sys.path.insert(0, str(Path(__file__).parent))
import review as R
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
MARGIN, KNEE = float(sys.argv[3]) if len(sys.argv) > 3 else 6.0, float(sys.argv[4]) if len(sys.argv) > 4 else 0.25
F = R.Faces()
v = R.vstream(R.probe(src)); W, H = int(v["width"]), int(v["height"])
full = R.decode(src, None, None, W, H, R.matrix_of(v, "bt709"))
small = R.decode(src, None, None, R.TW, R.TH, R.matrix_of(v, "bt709"))
sx = W / R.TW
T = None
out = []
last = None
for i, (f, s) in enumerate(zip(full, small)):
    fc = R.label_faces(s, [x for x in F.detect(s, small=True) if float(x[3]) >= 30]).get("lin_wan")
    last = fc if fc is not None else last
    lab = cv2.cvtColor(f.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)
    if last is not None:
        if T is None:
            ck = R.cheek_roi(last, s.shape)
            T = R.face_colour(s, ck)["a_p95"] + MARGIN
        x, y, w, h = (float(u) * sx for u in last[:4])
        m = np.zeros((H, W), np.float32)
        cv2.rectangle(m, (int(x - .25 * w), int(y - .1 * h)), (int(x + 1.25 * w), int(y + 1.45 * h)), 1.0, -1)
        m = cv2.GaussianBlur(m, (0, 0), 0.15 * w)
        a = lab[..., 1]
        over = np.maximum(a - T, 0)
        lab[..., 1] = a - m * over * (1 - KNEE)
    rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    out.append((np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8))
enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", "24", "-i", "-",
                        "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-c:v", "libx264", "-crf", "14",
                        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", str(dst)], stdin=subprocess.PIPE)
for f in out:
    enc.stdin.write(f.tobytes())
enc.stdin.close(); enc.wait()
print("T", T, "->", dst)
