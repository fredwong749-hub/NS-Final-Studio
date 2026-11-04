"""W45（总调度 11-04 05:0x，W43 查实）：gpu36 看图 :8870 固定 GPU1（GPU0 跑 Pika 19.3 GB，同卡争显存 → score_infra）。
三处必须一致：config/vqa.json model.gpus、resident_sync.vqa_env / vqa_services（vqa_guard 拉起参数）、tools/vqa/deploy_offline.sh（服务器启动脚本）。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/autopilot"))
sys.path.insert(0, str(ROOT / "tools/netfix"))
import resident_sync as RS  # noqa: E402


def _cfg():
    return json.loads((ROOT / "config/vqa.json").read_text(encoding="utf-8"))["model"]


def test_config_pins_gpu36_vqa_to_gpu1():
    m = _cfg()
    assert m["gpus"] == [1] and m["comfy_ports"]["1"] == 8189


def test_vqa_guard_launch_env_matches_config(monkeypatch):
    monkeypatch.setattr(RS, "ROOT", ROOT)
    e = RS.vqa_env()
    assert e["VQA_GPUS"] == "1" and e["VQA_COMFY"] == "1:8189"
    svc = {x["name"]: x for x in RS.vqa_services("gpu36")}
    assert svc["vqa"]["env"]["VQA_GPUS"] == "1" and svc["vqa"]["env"]["VQA_COMFY"] == "1:8189"
    assert svc["anomaly"]["env"]["CUDA_VISIBLE_DEVICES"] == "1"              # 人数检测同在 GPU1（合计 < 24 GB）


def test_deploy_offline_script_matches_config():
    sh = (ROOT / "tools/vqa/deploy_offline.sh").read_text(encoding="utf-8")
    line = next(ln for ln in sh.splitlines() if 'SELF" = gpu33' in ln and "VQA_GPUS" in ln)
    m = re.search(r'else ENV="VQA_GPUS=([\d,]+) VQA_COMFY=([\d:,]+)"', line)
    assert m, line
    gpus = [int(x) for x in m.group(1).split(",")]
    assert gpus == _cfg()["gpus"] and 2 not in gpus
    assert m.group(2) == ",".join(f"{g}:{_cfg()['comfy_ports'][str(g)]}" for g in gpus)


def test_vqa_env_fallback_is_gpu1_never_gpu2(monkeypatch, tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/vqa.json").write_text(json.dumps({"model": {"port": 8870}}), encoding="utf-8")
    monkeypatch.setattr(RS, "ROOT", tmp_path)
    assert RS.vqa_env()["VQA_GPUS"] == "1"
    (tmp_path / "config/vqa.json").write_text(json.dumps({"model": {"gpus": [2]}}), encoding="utf-8")
    assert RS.vqa_env()["VQA_GPUS"] == "1"
