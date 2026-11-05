# 工人发版约定（交付清单 + 文件租约）

目的：并行工人改重叠文件时，发版不再因“清单先拼、伴随文件后到 / 未跟踪伴随文件漏掉”拆刀（cut I 拆 3 刀的根因）。

## 工人怎么做
1. 开工前租文件（建议性，不锁文件系统，默认 6h 过期，glob 可用）：
   `python tools/qa/system_version.py lease take --worker CODER-X --paths "services/agent/*.py" tests/test_x.py`
   退出码 3 = 租到了但和别人重叠，先去 CHANNEL 协调。`lease list` 查看，`lease release --worker CODER-X`（可加 --paths）还租。
2. 交付时写 `data/system_versions/deliverables/<worker>-<YYYYMMDD>.json`：
   `{"schema":"nsfs.deliverable/1","worker":"CODER-X","files":[...],"tests":[...],"deletes":[],"depends_on":["<别的清单id>"],"default_off_switches":["开关路径 = 默认值"],"notes":""}`
   files / tests 必须含全部伴随文件：新模块、新配置、新测试、被引用的未跟踪文件。
3. 自检：`python tools/qa/system_version.py manifest-check <id>`，退出码 0 才算交付；再在 CHANNEL 记 ACK（写明清单 id）。

## manifest-check 查什么
- 文件都存在；记录 blob（写 `data/system_versions/pins/<id>.json`，并 `git hash-object -w` 入库，之后工作树被别人改也不影响拼树）。
- 伴随缺口（error）：清单内文件 import / 引用了未跟踪、又不在任何清单里的文件。
- 重叠（error）：两份清单含同一文件但 blob 不同；blob 相同只警告。
- depends_on 指向不存在的清单（error）；deletes 的文件仍在（error）。
- 别人租着的文件（warning）。

## 总调度 / 发版
- 手工：`system_version.py cut --manifests <id1> <id2> [--dry]`（HEAD + 钉住的 blob 拼树，有 error 拒绝）。
- 自动：release_request.json 写 `"manifests": ["<id>", ...]` 代替 `"list"`（其余字段不变），release_tick 同样先 manifest-check 再拼树。
- 发完后清单留在 deliverables/ 作账，不删。
