# 工人在 gpu33 上跑测试 / 诊断（W45 SERVER-DEV，2026-11-04）

项目方原话：“笔记本本来不适合做任务重的开发,gpu那2台服务器内存那么大,gpu 3090那么多卡,你不用,在这台笔记本做干嘛?”

**标准用法（所有工人）：笔记本只改代码、读结果；pytest / arch_scan / 诊断脚本一律走 `tools/qa/remote_pytest.py` 在 gpu33 上跑。**

## 一行用法

```bash
# 在仓库根（WSL bash 用 python3；PowerShell 用 .venv\Scripts\python.exe）
python3 tools/qa/remote_pytest.py -q tests/test_a.py tests/test_b.py        # ≥2 个测试文件自动 -n 16
python3 tools/qa/remote_pytest.py -q -n 24 tests/test_producer*.py -k canary  # 其余参数原样交给 pytest
python3 tools/qa/remote_pytest.py --cmd '$PY tools/qa/arch_scan.py --files tools/x.py --check'
python3 tools/qa/remote_pytest.py --cmd '$PY tools/debug/某诊断.py --dry'    # 任意命令：$PY = 服务器 venv，cwd = 副本根
python3 tools/qa/remote_pytest.py --no-data -q tests/test_pure_unit.py       # 纯单元测试：不接数据目录，更快
python3 tools/qa/remote_pytest.py --evidence -q tests/test_x.py              # 同 cut 口径：带笔记本数据镜像（结论与笔记本可比）
```

输出原样实时带回，退出码照传（pytest 的 rc；连接/准备失败 = 2，远端任务丢失/超时 = 3）。

## 它做了什么

1. 把**此刻的工作树**（.gitignore 口径，含你没提交、没跟踪的新文件；不动真 index）写成一棵临时 git 树。
2. 按 git blob sha 问服务器缺哪些文件：服务器先在自己的上一份副本里找（硬链，不占空间），再在 producer 仓库里找（**只复制、不硬链**，副本里怎么写都改不到生产代码）。**只推缺的**——笔记本→服务器链路只有约 170 KB/s，整棵树 390 MB 推不动；平时一次只推几个到几十个文件。
3. 在 `cut_snapshots/_dev/<时间>/` 拼出完整副本（tests/ 齐全），数据目录（data/、assets …，按 cut 快照同口径）从 producer 仓库硬链进来，不带 pid / 锁 / 心跳文件。
4. 用独立 venv（`config/qa/remote_dev.json` remote_python：pytest、xdist、CPU 版 torch 等对齐笔记本 .venv 包表）在 `nice 10`、`CUDA_VISIBLE_DEVICES=` 空下跑——不碰任何 GPU（含坏卡 gpu33:2），不和 producer 抢 CPU。
5. 后台跑（新会话，ssh 断了也不停），笔记本每 5 秒拉一次增量输出。

实测（11-04 03:3x）：5 个测试文件 106 个用例，准备 10–40 s（推 3–11 个文件）+ 运行 3 s，合计 37–60 s。

## 注意

- 服务器是 Linux：写死 Windows 路径 / `os.name == "nt"` 分支的测试会和笔记本结果不同——那是真问题（服务器才是生产环境），按 Linux 修。
- 数据是**服务器上的真实数据**（producer 在用的），不是笔记本的。依赖笔记本独有数据（如 data/sysarch/baseline.json、data/feedback/…）的测试/脚本在服务器上会读不到——报给 W45 / 总调度，加进同步清单，不要退回笔记本跑。
- 副本里数据是硬链：测试往数据文件**原地写**会写到 producer 的数据上（与笔记本 cut 快照同一风险）。测试一律写 tmp_path；real-data-guard 会报。
- 不删任何东西：副本留在 `_dev/` 下（硬链为主，几乎不占空间），由总调度定期清理。
- 服务器上 W45 只写两个目录：`cut_snapshots/`（含 `_dev/`）与 `w45/`（venv、inbox）。producer 的仓库与 venv 不动。
- 路径、并行数、轮询间隔都在 `config/qa/remote_dev.json`；改它不用改代码。

## 发版七门（总调度用）

`system_version.py cut [--dry] [--tree T] --on gpu33`：七门在 gpu33 跑，结果与每门耗时进 cut 报告；commit / tag / push 仍在笔记本。
详见 `tools/qa/remote_gates.py` 顶部说明与本目录 SMOKE_ON_SERVER.md。
