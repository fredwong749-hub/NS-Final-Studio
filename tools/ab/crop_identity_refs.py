import cv2, hashlib, json, sys
from pathlib import Path
R = Path(r"D:\NS-Final Studio")
SRC = {"lin_wan": "data/ab/char_sheets/lin_wan/lin_wan_sheet_A_s202.png",
       "gu_chen": "data/ab/char_sheets/gu_chen/gu_chen_sheet_T_s101.png",
       "chen_yu": "data/ab/char_sheets/chen_yu/chen_yu_sheet_T_s202.png"}
det = cv2.FaceDetectorYN.create(str(R / "models_cache/vision/face_detection_yunet_2023mar.onnx"), "", (320, 320), 0.6)
out = {}
for c, rel in SRC.items():
    im = cv2.imread(str(R / rel)); H, W = im.shape[:2]
    panel = im[:, : int(W * 0.31)]            # 左栏：大头特写
    ph, pw = panel.shape[:2]
    det.setInputSize((pw, ph)); _, f = det.detect(panel)
    x, y, w, h = max(f, key=lambda r: r[2] * r[3])[:4]
    cx = x + w / 2
    top = max(0, int(y - 0.75 * h)); bot = min(ph, int(y + h * 1.0))   # 发顶 → 下巴下沿，不含领口
    side = int((bot - top) * 1.05 / 2)
    l, r = max(0, int(cx - side)), min(pw, int(cx + side))
    crop = panel[top:bot, l:r]
    d = R / "data/assets/identity_refs" / c; d.mkdir(parents=True, exist_ok=True)
    p = d / f"{c}_face_ref2va.png"
    cv2.imwrite(str(p), crop)
    b = p.read_bytes()
    out[c] = {"file": str(p.relative_to(R)).replace("\\", "/"), "source_sheet": rel, "sheet_sha256": hashlib.sha256((R / rel).read_bytes()).hexdigest(),
              "sha256": hashlib.sha256(b).hexdigest(), "size": [crop.shape[1], crop.shape[0]], "crop_box_in_panel": [l, top, r, bot],
              "method": "YuNet 2023mar 取左栏最大脸框；上扩 0.75×脸高（含发顶）、下到 1.0×脸高（下巴下沿，不含领口/项链），宽=高×1.05 居中"}
    print(c, out[c]["size"], out[c]["sha256"][:12])
json.dump(out, open(R / "data/assets/identity_refs/manifest_draft.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
