"""ASSETMASTER 第 2 步：缺图单品的"产品参考图"候选（白底 / 中性底，写实材质，768×1344 竖屏统一规格）。

读 data/assetmaster/todo.json（scan.py 产出），只做：已登记（P1 或 look_extras 暂定）且 状态=缺图/待确认 的单品；
妆容不做产品图（妆容要上脸，走身份编辑）；项目方给过真实参考图的单品不重出。
同一角色同名单品（如红绳在陈宇 A/B/C）只出一组。每件 3 个候选：正面 ×2 seed + 侧 45° ×1。
模型：BAKEOFF 结论前先用 Qwen-Image 2.1 + 默认预设 leica_sstar（与场景底图同一套：ns_render.image_params）。
质检（postflight，出图机器原地打分）：0 人脸、0 文字（rapidocr）、Laplacian 清晰度；按 (无脸无字, 清晰度) 自动选暂定。
输出 data/assetmaster/items/<char>/<slug>/{front_s*,side_s*}.png + data/assetmaster/items.json；不自动登记——总调度审后再登记。

用法：.venv/Scripts/python.exe tools/assetmaster/gen_items.py [--lanes gpu33:0,gpu33:1,gpu33:3] [--only lin_wan] [--dry]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/render_router", "services/agent", "packages/schema", "tools/pipeline", "tools/series10_imggen"):
    sys.path.insert(0, str(ROOT / p))

OUT = ROOT / "data" / "assetmaster" / "items"
RES = ROOT / "data" / "assetmaster" / "items.json"
ALL_LANES = {"gpu33:0": "http://127.0.0.1:18188", "gpu33:1": "http://127.0.0.1:18189", "gpu33:3": "http://127.0.0.1:18191",
             "gpu36:0": "http://127.0.0.1:18288", "gpu36:1": "http://127.0.0.1:18289", "gpu36:2": "http://127.0.0.1:18290"}
GENDER = {"lin_wan": "女款", "ch_a_lan": "女款", "gu_chen": "男款", "chen_yu": "男款"}
# 规格补充（只补材质 / 形制常识，不改登记名）；项目方硬规则：B7 6mm 针形跟、B8 漆皮镜面
SPEC = {
    "透明12cm细高跟": "12厘米透明PVC鞋面侧口开边细高跟鞋，鞋跟直径约6毫米、细如一根筷子的针形细跟",
    "黑色漆皮束腰": "黑色高亮镜面漆皮束腰，表面湿润光泽，镜面反射清晰，高光锐利",
    "腰侧九枚细金属环": "正好九枚（3行×3列整齐排列，共9枚，不多不少）直径约1厘米的细银色不锈钢穿孔圈环，抛光金属",
    "5厘米超长透明镶钻水晶甲": "一套10片5厘米超长透明水晶甲片，甲面镶满细碎透明钻石饰品，尖长甲型，摆在展示架上",
    "细银链": "一条极细的925银项链，细链环，没有吊坠",
    "红绳手链": "一条细红绳编织手链，简单打结",
    "红绳": "一条细红绳，系成手腕绳的样子，简单打结",
    "旧银戒": "一枚素面银戒指，表面有细小划痕和使用痕迹的旧银",
    "雾蓝针织长裙": "雾蓝色细针织长裙，修身贴身款，长度到小腿",
    "米白衬衫": "米白色女式衬衫，真丝质感，修身",
    "深灰西装裙": "深灰色西装面料铅笔裙，高腰，长度到膝上",
    "短款西装外套": "女式短款西装外套，深灰色，修身，长度到腰",
    "白球鞋": "一双白色皮质低帮球鞋，干净简洁",
    "深灰西装": "男式深灰色西装外套与西裤套装，修身剪裁",
    "黑色高领毛衣": "男式黑色细针织高领毛衣",
    "白衬衫": "男式白色衬衫，挺括棉质",
    "黑西裤": "男式黑色西裤，修身直筒",
    "黑色皮鞋": "男式黑色皮质系带正装皮鞋",
    "深蓝浴袍": "深蓝色厚棉毛巾浴袍，系带",
    "室内拖鞋": "一双深色简洁室内拖鞋",
    "浅灰卫衣": "男式浅灰色连帽卫衣",
    "牛仔裤": "男式蓝色直筒牛仔裤",
    "白色帆布鞋": "一双白色低帮帆布鞋",
    "米色针织衫": "男式米色圆领针织衫",
    "卡其裤": "男式卡其色休闲长裤",
    "棕色皮鞋": "男式棕色皮质休闲皮鞋",
    "白T恤": "男式白色纯棉圆领T恤",
    "运动裤": "男式灰色抽绳运动长裤",
    "黑色工作围裙": "黑色帆布工作围裙，挂脖系带，带口袋",
    "黑色长袖": "女式黑色修身长袖T恤",
    "黑色短靴": "女式黑色皮质短靴，低跟",
    "皮手套": "一副黑色皮质工作手套",
    "军绿工装": "女式军绿色工装连体裤（背带工装）",
    "黑色背心": "女式黑色修身背心",
    "马丁靴": "一双黑色皮质马丁靴，八孔系带",
    "阔腿裤": "女式黑色阔腿长裤",
    "黑色吊带": "女式黑色细肩带吊带上衣",
    "黑色平底鞋": "一双女式黑色皮质平底鞋",
}
PRODUCT = ("专业电商产品摄影，商品完整居中入画，浅灰色无缝背景，柔和箱灯，真实材质与缝线细节清晰，画面中没有人、没有模特、"
           "没有任何人体和皮肤，无文字无水印无标签，竖构图")
JEWEL = ("珠宝产品微距摄影，饰品平放在浅灰色无缝背景上，柔和箱灯与清晰的金属反光，画面中没有人体和皮肤，无文字无水印，竖构图")
VIEWS = [("front", 9101, "正面展示"), ("front", 9102, "正面展示"), ("side", 9103, "侧面45度展示")]


def slug(char: str, name: str) -> str:
    return hashlib.md5(f"{char}:{name}".encode("utf-8")).hexdigest()[:8]


def prompt_for(it: dict, view: str) -> str:
    base = SPEC.get(it["name"], it["name"])
    g = "" if re.search("[男女]式|一双|一副|一枚|一条|一套|九枚", base) else GENDER.get(it["char"], "")
    if it["slot"] in ("jewelry", "piercing", "nails"):
        style = JEWEL
        hold = ""
    elif it["slot"] == "shoes":
        style, hold = PRODUCT, "鞋子成双摆放在地面上，"
    else:
        style, hold = PRODUCT, "挂在透明隐形人台上，"
    return f"{g}{base}的产品参考图，{hold}{view}。{style}"


def items_to_make(only: str | None) -> list[dict]:
    todo = json.loads((ROOT / "data" / "assetmaster" / "todo.json").read_text(encoding="utf-8"))["todo"]
    seen, out = set(), []
    for x in todo:
        if x["slot"] in ("makeup", "prop") or not x["registered"]:
            continue
        if only and x["char"] != only:
            continue
        k = (x["char"], x["name"])
        if k in seen:
            for o in out:
                if (o["char"], o["name"]) == k:
                    o["looks"].append(x["look"])
                    o["shots"] = sorted(set(o["shots"]) | set(x["shots"]))
            continue
        seen.add(k)
        out.append({"char": x["char"], "name": x["name"], "slot": x["slot"], "looks": [x["look"]], "shots": x["shots"],
                    "slug": slug(x["char"], x["name"])})
    return out


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--lanes", default="gpu33:0,gpu33:1,gpu33:3")
    ap.add_argument("--only")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--pick-only", action="store_true")
    a = ap.parse_args(argv)
    if a.pick_only:
        res = json.loads(RES.read_text(encoding="utf-8"))
        pick(res)
        RES.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    its = items_to_make(a.only)
    res = json.loads(RES.read_text(encoding="utf-8")) if RES.exists() else {}
    tasks = []
    for it in its:
        r = res.setdefault(it["slug"], {k: it[k] for k in ("char", "name", "slot", "looks", "shots", "slug")})
        r.update({k: it[k] for k in ("looks", "shots")})
        for view, seed, vz in VIEWS:
            if not (r.get("cands", {}).get(f"{view}_s{seed}") or {}).get("file"):
                tasks.append((it, view, seed, prompt_for(it, vz)))
    print(f"单品 {len(its)}，待出 {len(tasks)} 张", flush=True)
    if a.dry:
        for t in tasks[:6]:
            print(t[0]["char"], t[0]["name"], t[1], t[2], t[3])
        return 0
    from ns_render import image_params as IP
    from ns_render import workflows as W
    import imggen as IG
    eff = IP.resolve("leica_sstar", {"loras": [{"name": "krea2_film_texture_qwen21.safetensors", "strength": 0.5}]})
    lk = threading.Lock()

    def save():
        RES.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    def worker(lane, url):
        c = IG.Lane(lane, url)
        while True:
            with lk:
                if not tasks:
                    return
                it, view, seed, p = tasks.pop(0)
            wf = W.qwen_t2i(p, "人物，模特，人体，皮肤，手，脸，文字，水印，标签，logo", 768, 1344, seed,
                            f"assetmaster/{it['slug']}_{view}_s{seed}", m=W.QwenModel(), loras=[])
            wf = IP.apply(wf, eff, set())
            dest = OUT / it["char"] / it["slug"] / f"{view}_s{seed}.png"
            try:
                try:   # GPU 任务归属标签（K-OPS-G01）；出错就不带标签
                    _tag = IG._ct().make("ASSETMASTER", "sheet", obj=f"{it['char']} · {it.get('name') or it['slug']}",
                                         label=f"道具 {view} s{seed}", job=f"{it['slug']}_{view}_s{seed}")
                except Exception:  # noqa: BLE001
                    _tag = None
                pid = c.submit(wf, front=True, tag=_tag)
                t0 = time.time()
                while True:
                    time.sleep(4)
                    r = c.fetch(pid, dest)
                    if r:
                        break
                rec = {"view": view, "seed": seed, "prompt": p, "lane": lane, "status": r, "secs": round(time.time() - t0, 1),
                       "host_path": getattr(c, "last_host_path", None), "preset": "leica_sstar", "model": "qwen-image-2.1"}
                if r == "ok":
                    post = IP.post_file(dest, eff)
                    rec["raw"] = str(dest.relative_to(ROOT)).replace("\\", "/")
                    rec["file"] = str(Path(post["path"]).relative_to(ROOT)).replace("\\", "/") if post else rec["raw"]
                with lk:
                    res[it["slug"]].setdefault("cands", {})[f"{view}_s{seed}"] = rec
                    save()
                print(time.strftime("%H:%M:%S"), lane, it["char"], it["name"], view, seed, r, rec["secs"], flush=True)
            except Exception as e:  # noqa: BLE001
                print("ERR", lane, it["name"], view, seed, repr(e)[:200], flush=True)

    lanes = {n: ALL_LANES[n] for n in a.lanes.split(",")}
    th = [threading.Thread(target=worker, args=(n, u)) for n, u in lanes.items()]
    for x in th:
        x.start()
    for x in th:
        x.join()
    pick(res)
    save()
    return 0


def skin_frac(path) -> float:
    """产品图里不该有人体：YCrCb 肤色像素占比（透明人台不算肤色）。K-AST-229"""
    import cv2
    import numpy as np
    im = cv2.imread(str(path))
    im = cv2.resize(im, (256, int(256 * im.shape[0] / im.shape[1])))
    y = cv2.cvtColor(im, cv2.COLOR_BGR2YCrCb)
    m = (y[..., 1] >= 138) & (y[..., 1] <= 173) & (y[..., 2] >= 77) & (y[..., 2] <= 127) & (y[..., 0] > 60)
    return round(float(m.mean()), 4)


def pick(res: dict):
    """postflight：0 人脸、0 文字、清晰度 → 选暂定（正面优先）"""
    import cv2
    import imggen as IG
    files = {f"frame:{s}/{k}": (None, v["lane"].split(":")[0], v["host_path"]) for s, d in res.items()
             for k, v in (d.get("cands") or {}).items() if v.get("host_path")}
    try:
        out = IG.qc_batch(files) if files else {"items": {}}
    except Exception as e:  # noqa: BLE001
        print("qc_err", repr(e)[:200])
        out = {"items": {}}
    for s, d in res.items():
        best = None
        skin_tone_item = any(w in d["name"] for w in ("米", "卡其", "棕", "透明", "肤", "裸"))   # 商品本身是肤色系：肤色检查不适用，人工目检
        d["skin_check"] = "人工目检（肤色系单品）" if skin_tone_item else "自动"
        for k, v in (d.get("cands") or {}).items():
            if not v.get("file"):
                continue
            q = out["items"].get(f"frame:{s}/{k}") or {}
            v["faces"] = len(q.get("faces", []))
            v["text"] = [t["text"] for t in q.get("text", [])]
            v["qc_ran"] = bool(q)
            g = cv2.cvtColor(cv2.imread(str(ROOT / v["file"])), cv2.COLOR_BGR2GRAY)
            v["lap_var"] = round(float(cv2.Laplacian(g, cv2.CV_32F).var()), 1)
            v["skin"] = skin_frac(ROOT / v["file"])
            # 首饰圈环会被 OCR 读成 0/O：只有字母数字混排或 ≥2 个不同字符才算文字
            txt = [t for t in v["text"] if len(set(t.replace("0", "O").upper())) >= 2]
            v["ok"] = v["qc_ran"] and v["faces"] == 0 and not txt and v["lap_var"] >= 20 and (v["skin"] < 0.03 or skin_tone_item)
            key = (v["ok"], v["view"] == "front", v["lap_var"])
            if best is None or key > best[0]:
                best = (key, k)
        if best:
            d["chosen"] = {"cand": best[1], "file": d["cands"][best[1]]["file"], "tentative": True, "ok": d["cands"][best[1]]["ok"]}


if __name__ == "__main__":
    sys.exit(main())
