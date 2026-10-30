# gpu3 阶段调度器（T46，claude-gpu3，2026-10-30）

依据：`docs/SOP_production.md`「★ 阶段闸门与资源优先级」。项目方规则：剧本 → 资产（含全部 LoRA）→ 首尾帧 → 视频 → 成片/4K，GPU 按阶段严格优先；上游闸门不过，下游不给卡；缺任何一项的镜头绝不出视频。

- 代码：gpu3 `ns-studio/scripts/ns_sched.py`（只用标准库，Python 3.10）
- 配置：gpu3 `ns-studio/config/ns_sched.json`（项目、消费者、人工基线）
- 测试：gpu3 `ns-studio/tests/test_ns_sched.py`
- 常驻单元：`ns-sched.service`（transient，每 5 分钟一轮，`Restart=on-failure`）
- 状态目录：`/root/.local/state/NS-Studio/`

## 1. 运行模式

| 文件 `scheduler_mode` 内容 | 行为 |
|---|---|
| 不存在 / `dry-run`（当前） | 只计算、只写计划和事件日志；**不写** `assign.*`、**不碰** `lend.*` |
| `active` | 另外写 `assign.gpuN.json` 和旧的 `lend.gpuN` |

切换不需要重启：`echo active > /root/.local/state/NS-Studio/scheduler_mode`。**切换前须经项目方批准。**

常用命令（在 `ns-studio/` 下）：

```
python3 scripts/ns_sched.py show                 # 最近一轮计划（人读）
python3 scripts/ns_sched.py once --no-write      # 现算一轮，只打印
python3 scripts/ns_sched.py compare --minutes 60 # 计划 vs 人工分配
python3 scripts/ns_sched.py may-use <名字> <gpu>  # 流水线问：这张卡是不是我的（退出码 0 = 是）
journalctl -u ns-sched -f
```

## 2. 分配契约

`/root/.local/state/NS-Studio/assign.gpuN.json`（**只有调度器写**）：

```json
{"gpu": 0, "stage": "S2", "consumer": "lw-img-lora", "project": "weita",
 "reason": "S2资产/LoRA 优先级最高的待办：…", "assigned_at": "2026-10-30T05:00:00Z", "expires_at": null}
```

- `consumer` 是配置里的消费者名；配置里还有 `lend_name`，即旧 lend 文本里用的名字。两个名字都算数。
- `expires_at` 可选。有值并且已经过期，就当作没有分配。
- 兼容旧流水线：在 active 模式下，同时写 `lend.gpuN`，文本以消费者的 `lend_name` 开头，例如 `lw-img-lora (ns-sched: S2 …)`。这样用 grep 找自己名字的流水线不用改。
  - 消费者的 `legacy` 为 `unlent` 时（首尾帧、视频渲染器），按旧约定**删除** `lend.gpuN`，因为对渲染器来说，没有 lend 文件的卡才是自己的。
  - 卡空闲（没有任何阶段需要）时，删除 assign 文件，并删除调度器认得的 lend 文件。
- **边界规则**：卡上有活着的 `gpu.lock.gpuN`、`train.lock.gpuN`（或 `.N`），或者流水线自己的占用文件（如 `jewellery/GPU_IN_USE_gpuN.json`，在 `jwl-pipeline` 运行期间有效），这张卡就算在运行中。调度器不改它的 assign 和 lend，只在计划里写下“到边界后给谁”（`next_at_boundary`）。等锁释放或单元停掉，下一轮再换。pid 已经死掉的锁算过期，不算持有。
- GPU 2 永不分配，写死在代码里（`NEVER = {2}`），配置改不掉。

### 流水线今后应该这样读分配

每领一个任务前（或每一镜之间）查一次。仍要照旧持有 `gpu.lock.gpuN`（O_EXCL，内容为 `pid:<pid> <名字>`），这样调度器知道这张卡正在跑。

bash：

```bash
S=/root/claude-kimi-ns-studio-v1/ns-studio/scripts/ns_sched.py
if python3 $S may-use lw-img-lora 0 >/dev/null; then echo "GPU0 是我的"; fi
```

Python：

```python
import json, time
from pathlib import Path
ST = Path("/root/.local/state/NS-Studio")
def my_gpus(names: set[str]) -> list[int]:
    out = []
    for g in (0, 1, 3):                      # 永远不含 2
        try:
            a = json.loads((ST / f"assign.gpu{g}.json").read_text())
        except (OSError, ValueError):
            continue
        if a.get("expires_at") and a["expires_at"] < time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()):
            continue
        if a.get("consumer") in names:
            out.append(g)
    return out
```

`may-use` 的判断顺序：先看 assign 文件；没有 assign 文件（调度器还在 dry-run）时，退回旧做法，看 lend 文本里有没有这个名字。所以流水线现在就可以改成调用 `may-use`，dry-run 和 active 两种模式下都能用。

## 3. 优先级

1. **阶段**：S1 剧本 > S2 资产/LoRA > S3 首尾帧 > S4 视频 > S5 成片/4K > AUX 声音。声音按 SOP 只用 CPU，只拿没有任何阶段要的空闲卡。
2. **剧**：按 `projects[].started` 从早到晚排。
3. **S2 内部**：先比 LoRA 能解锁哪个阶段。出图 LoRA 解锁 S3，排在只解锁 S4 的视频 LoRA（如 H3 身份 `lnwan01`）前面。同一类里，再按“还欠的触发词被多少镜头用到”排，多的优先（`weight`）。
4. **不来回抢卡**：一张空闲卡已经分给某个消费者，它还有待办，而且没有**更高阶段**在等这张卡，就继续给它。同一阶段内的排序只决定刚空出来的卡给谁。
5. 每个消费者最多占 `max_gpus` 张卡（默认 1；首尾帧和视频为 2）。
6. 只分给能跑的消费者：单元在运行，或者是 `planned: true` 的计划流水线（等借卡，比如 lw-img-lora、pose-lora）。有待办但单元暂停的（`demand_not_running`）不分卡。

S2 资产可以和 S1 同时做。S2 只和 S1 抢卡；按上面的阶段顺序，S1 先拿。真正被闸门挡住的是 S3、S4、S5。

## 4. 每个阶段的需求从哪来（每 5 分钟重算）

| 阶段 | 判断依据 |
|---|---|
| S1 | `kind: units` 消费者的单元在运行（weita：`weita-v3-run*`、`weita-v3-finish*`）。项目的 S1 闸门 = `s1.done_files` 都在、`fail_files` 都不在（weita：`tools/weita_v3/work/FINISH_DONE`）；每镜要素来自导入 JSON：img、motion、时长（`duration_source=script`）、sound、sound_h3、music_cue、成人镜头的 sound_intimate、本集 music_bgm |
| S2 | 每个 LoRA 消费者：它产出的 LoRA 文件不在 `ComfyUI/models/loras/`，并且（单元在运行，或 `planned`），并且 `requires` 都满足。分阶段的流水线（wardrobe：合成集 → 人审 `REVIEWED_*` → 训练）在等人审时算 `waiting_input`，不占卡。**触发词**：剧本（v3 优先，没有就用 v2）的每镜文字 + 导入 JSON 的 `img_triggers`/`motion_triggers` + v3 工作文件里的 `pose` 字段。注册表 = 剧本 spec 的「数据E」+ `LORA_REGISTRY.json`。验收 = 文件在磁盘，并且 `LORA_REGISTRY.json` 里 `accepted: true`（或 `status: accepted`），或 `lora_sanity.json` 里通过。剧本用到、但没有任何流水线产出的触发词，记为 `orphan` 事件 |
| S3 | 镜头满足：项目 S1 闸门已过，本镜 S1 要素齐全，本镜出图 LoRA 全部验收，首尾帧还没过闸门。“已过闸门” = `run/weita/epXX/frames/epXXsN.pick.json` 的 `regated` 为真、没有衔接失败、不是笔记本帧；或 `renders_gpu3/epXX/SN/status.json` 里 `frames_gated: true` |
| S4 | 镜头 100% 就绪：S3 已过闸门，S1 要素齐全，出图和视频 LoRA 全部验收，`status.json` 没有 `blocked_reasons`，还没有视频。**渲染器自己的就绪闸门 `weita_series.readiness()` 照常拒绝未就绪镜头**，调度器不重复执行这道闸门，只是不给卡 |
| S5 | `renders_gpu3/[<slug>/]epXX/qa.json` 的 `verdict == "pass"`，并且还没有 `epXX_4k.mp4` |

**拒绝**：下游单元正在跑，但它所在阶段的闸门没过（例如 `up4k-test` 在跑，却没有任何一集 qa pass），调度器不给它卡，并在 `scheduler_events.jsonl` 写一条 `refuse` 事件。同样的拒绝每小时最多记一次。

## 5. 输出文件（都在 `/root/.local/state/NS-Studio/`）

| 文件 | 内容 |
|---|---|
| `scheduler_plan.json` | 最近一轮的完整计划（`ns_sched.plan/v1`）：每张卡的 `assigned`、`stage`、`locked`、`why`、`next_at_boundary`、当前占用（`current`/`current_via`）、人工基线是否一致、active 模式下会写什么（`would_write`）；各阶段需求，各消费者状态与原因，各项目的 S1–S5 闸门统计，拒绝和孤儿触发词 |
| `scheduler_plans.jsonl` | 每轮一行的精简记录，供 `compare` 用 |
| `scheduler_events.jsonl` | `assign`、`hold`（卡的决定变化时写）；`refuse`、`orphan`、`queued`（每小时最多一次） |
| `scheduler_mode` | `dry-run` / `active` |
| `assign.gpuN.json` | 只在 active 模式下写 |

画布：gpu3 桥（`services/canvas_api`）的 `GET /api/gpu3/gpus` 给每张卡加了 `scheduler` 字段，包含 `mode`、`assign`、`planned`、`stage`、`locked`、`why`、`next`；新增 `GET /api/gpu3/scheduler`，返回完整计划，只读。代码已同步到 gpu3，`nsfs-canvas-bridge` 下次重启后生效（本任务按规定没有重启它）。

## 6. 新剧怎么接入

在 `ns_sched.json` 里加：

1. `projects[]` 一项：`slug`、`started`（立项日期，决定剧与剧之间的先后）、`script_import`（`projects/<slug>/data/import/script_v2.json` 的 gpu3 镜像）、`script_md`（v3 在前、v2 在后）、`lora_spec_md`（含「数据E」）、`s1.done_files`、`renders`（`renders_gpu3/<slug>`）、`run_dir`、`lora_sanity`。
2. `consumers[]` 里加这部剧的消费者，`project` 填 slug：
   - S1：`kind: units`，单元为它的剧本 LLM 任务；
   - S2：`kind: lora`，填 `produces`（触发词 → 文件），或填 `produces_pattern`；新流水线还没建单元时，用 `planned: true` + `requires`；
   - S3、S4、S5：`kind: frames`、`video`、`upscale`，填它的渲染单元。
   - 每个消费者都要写：`gpus`（偏好顺序，不能写 2）、`match`（锁或 lend 文本里能认出它的字样）、`lend_name`、`legacy`（`lend` 或 `unlent`）。
3. 新流水线一律用 `ns_sched.py may-use <lend_name> <gpu>` 选卡，跑的时候持有 `gpu.lock.gpuN`，不要自己写 lend 文件。

配置每轮都会重新读，改完不用重启 `ns-sched`。

## 7. 流水线接入状态（2026-10-30 03:30Z）

统一接入方式：`ns-studio/scripts/ns_assign.py`（只用标准库）。

- Python：`ns_assign.assign_state(names, gpu)` 返回 `mine`、`other` 或 `none`。
- bash：`python3 ns_assign.py <名字,名字> <gpu>`，打印同样三个值，退出码 0、1、2。
- `none` 表示没有有效的 assign 文件（dry-run、调度器停了或分配已过期），流水线**照旧走原来的 lend/锁逻辑**。所以 dry-run 期间，改过的流水线行为完全不变。
- `other` 表示卡分给了别人，不管 lend 文件写的是什么都不能用。
- `mine` 表示卡是自己的，但仍要照旧检查和持有锁。

| 流水线 | 改了哪里 | 状态 |
|---|---|---|
| wardrobe | `tools/comfy_gen.py` 的 `eligible()`、`tools/wardrobe_train.sh` 的选卡循环 | **已改**（备份 `*.bak-t46-20261030`）。`pipe_clear.sh`、`pipe_clothes.sh` 本身不选卡（训练交给 `wardrobe_train.sh`），没有改 |
| nsaudio | `scripts/audio_post.py` 的 `gpu_available()` | **已改**（已备份） |
| lw-lora | `tools/lw_lora/lw_pipeline.sh` 的 `pick_gpu()`，GPU 顺序 0、3、1 | **已改**（已备份）。正在跑的进程用的是旧文件，单元下次启动才生效 |
| lw-img-lora | `data/train/lin_wan_qi/tools/lw_qi_pipeline.sh` 的等卡条件；结束时写 `lend.gpu0=pose-lora` 只在 dry-run 下执行 | **已改**（已备份）。同样下次启动生效 |
| pose（pose-lora、pose-blender） | — | **按政策停止**（不支持生成露骨内容）。调度器里标为 `halted (policy)`：不分卡，不排队，不算孤儿，`may-use` 一律拒绝。补丁 `t46_patches/pose_pipeline.sh.patch` **不打** |
| jwl、jwl-fix | — | 同上，`halted (policy)`；`t46_patches/jwl_comfy.py.patch` **不打** |
| fredw-d9 资产 | `tools/gpu_grab.py` 每个任务前调 `ns_sched.py may-use fredw-d9-assets <gpu>` | fredw-d9 负责；调度器这边已就绪 |

所有备好的补丁都用 `patch --dry-run` 验证过能打上，打上后能编译或通过 `bash -n`。

## 8. 短任务消费者（`short_jobs: true`）

适用于 `char-variety`、`fredw-d9-assets`、`pose-blender`、`jwl-fix`。

- 调度器不提前给短任务分卡，也不让它们排队。它们每个任务前调用 `may-use` 问一次。
- `may-use` 只在以下条件**全部**满足时放行：
  - 卡在这个消费者的 `gpus` 里；
  - 卡上没有活着的锁；
  - 最新计划（15 分钟内）没有把卡给非短任务；
  - 也没有 S1 或长的 S2 训练在等这张卡（`next_at_boundary`）。
- 所以 S1 和长训练永远优先于短的资产任务。计划过期时只看锁和 lend。
- 同一阶段里，短任务的优先级排在长任务后面。
- 锁文本可以不带 pid，例如 `fredw-d9 <job>`。这种锁超过消费者的 `lock_ttl_s`（20 或 30 分钟）就算过期。
- 配置支持 `deferred` 字段（暂缓：不排队，不算孤儿）。
- 配置支持 `halted` 字段（停止：同上，并且 `may-use` 拒绝）。目前 jwl、jwl-fix、pose-lora、pose-blender 都是 `halted (policy)`。依赖这些 LoRA 的镜头在 S3 闸门里一直标为“LoRA 未验收”，不会出帧，也不会出视频。

## 9. lend 文件的其他写入者（active 模式下都要停）

| 写入者 | 做什么 | 处理 |
|---|---|---|
| `lend-gpu0-after-v3c.service` 一类的 watcher | v3 完成后写 `lend.gpu0` | 现在已经不在运行。active 后不再新建这类 watcher，分卡交给调度器 |
| `tools/weita_v3/v3_finish.sh` | 结束时删除 `lend.gpu0`（和自己的 `gpu.lock.gpu0`） | 补丁 `t46_patches/v3_finish.sh.patch`：active 模式下只删自己的锁 |
| `tools/weita_v3/v3_finish5.sh`（正在跑的 `weita-v3-finish5`） | 结束时写 `lend.gpu0 = lw-img-lora`（dry-run 期间正是靠它把 GPU0 交给 lw-qi） | 补丁 `t46_patches/v3_finish5.sh.patch`：active 模式下不写 |
| `scripts/weita_series.py` 的 `lend()`、`unlend_all()`、`free_slots()` | 空闲时把卡借给训练，开工时收回 | 补丁 `t46_patches/weita_series.py.patch`：active 模式下这三处都不写也不删（`_sched_active()`）。系列渲染器目前暂停中 |
| `lw_qi_pipeline.sh` | 结束时写 `lend.gpu0=pose-lora` | 已改：active 模式下不写 |
| 人手 / agent 手写 | — | active 后禁止，改调度器配置 |

## 10. 切 active 前的检查清单

1. [x] dry-run 跑满 1 小时（02:22–03:22Z，13 轮），与人工分配逐卡对比。GPU3 13/13 一致。GPU0 和 GPU1 各有 2 次不一致，都已查明原因并修好（见 TASKS T46）。
2. [x] wardrobe、nsaudio、lw-lora、lw-img-lora 已能读 assign（没有 assign 时行为不变）。
3. [x] pose、jwl：按政策停止（`halted (policy)`），补丁不打。
4. [ ] `weita-v3-finish5` 结束（FINISH_DONE）后：打上 `v3_finish.sh`、`v3_finish5.sh`、`weita_series.py` 三个补丁；重启**仍在等卡**的 lw-lora 和 lw-qi（已经在跑的不重启，下次启动生效）；重启 `nsfs-canvas-bridge`。以上已写成脚本 `ns-studio/scripts/t46_after_v3.sh`，它会一直等到 FINISH_DONE 再动手；遇到 FINISH_BLOCKED 就什么都不做。启动方式：`systemd-run --unit=t46-after-v3 /root/claude-kimi-ns-studio-v1/ns-studio/scripts/t46_after_v3.sh`。**尚未启动**：权限系统拒绝 agent 启动会重启运行中单元的任务，需由协调人或项目方执行。
5. [ ] 同第 4 步。
6. [ ] 同第 4 步。
7. [ ] 项目方批准后执行 `echo active > /root/.local/state/NS-Studio/scheduler_mode`。下一轮（≤5 分钟）开始写 assign 和 lend。回退：`echo dry-run > …/scheduler_mode`，再删掉 `assign.gpu*.json`。

已知限制：
- 不带 pid 的锁要靠 TTL 才能判定过期。
- `jwl-pipeline` 自己的 `GPU_IN_USE_gpu1.json` 只在该单元运行期间有效。
- `LORA_REGISTRY.json` 还不存在，所以 S3 闸门里“LoRA 已验收”目前一个都不成立。
