# DATA_MAP §6 第 2 项：资产中心的造型字母和分组改成和出图同源（DATAALIGN 交给 ASSETUX 的补丁）

## 现状

- 后端 `/api/episodes*` 的 `shots[].characters[]` 已改成和出图同源（`ns_api/shot_cast.py`，:8800 已重启）。各字段现在的含义：

  | 字段 | 含义 |
  |---|---|
  | `look_label` | A / B / C，来自 `shot_looks.json`；资产中心整集排期优先 |
  | `cast_source` | `"script_cast"` |
  | `presence` | 在画 / 局部 |
  | `look_id` | 仍是旧库的 `<角色>-default`，只为兼容旧接口保留 |

- 下面四处还在按 `look_id` 分组：
  - `AssetsPage.tsx:41` `buildUsage`
  - `assets/center.ts:104` `usageOf.byLook`
  - `assets/AssetCenter.tsx:407` 本集造型条

  所以“哪集用哪套 / 几镜”显示的是旧库排期（一律是“默认”）。人物页 `character_hub._schedule` 读的是 `shot_looks.json`，两边对不上。

- `v3/looks.ts:17` `lookLetter` 在没有 label 时，按旧库列表顺序编字母。

## 建议的改法

只改分组键和字母来源，不删功能：

```ts
// 一处共用（建议放 v3/looks.ts）：镜头卡人物 → 本镜造型键
export const shotLookKey = (c: { look_id: string | null; look_label?: string; cast_source?: string }) =>
  c.cast_source ? (c.look_label ? `s10:${c.look_label}` : "") : c.look_id ?? "";
```

1. **`AssetsPage.tsx` `buildUsage`**：把 `const k = c.look_id ?? "";` 改成 `const k = shotLookKey(c);`。
2. **`center.ts` `usageOf`**：把 `if (c.look_id) { … byLook.set(c.look_id, …) }` 改成 `const k = shotLookKey(c); if (k) { … byLook.set(k, …) }`。
3. **`AssetCenter.tsx:407`**：把 `r.looks.set(c.look_id, c.look_label || c.look_name)` 改成 `r.looks.set(shotLookKey(c), c.look_label || c.look_name)`。
4. **展示 series10 造型的卡片**（人物页 / 新造型卡用 `character-hub` 的 looks，id 为 A/B/C）：按 `s10:<id>` 去查 `byLook`。旧库形象卡在 series10 下会显示 0 镜，这个数是真实的，因为出图不用旧库形象。
5. **`lookLetter`**：有 `lk.label` 就用；没有就显示 `?`，不再按列表顺序编 A/B/C。旧库“默认”形象如果要显示 A，请在 `looks.json` 里给它写 `label`，不要在前端编。

## 验证

- 跑 `.venv/Scripts/python.exe tools/qa/data_parity.py --all`，应为 PASS。
- 资产中心第 3 集：
  - 林晚应是 A（S1–S2）、B（S3–S7）；
  - 顾沉应是 B。
  - 和 `/api/character-hub/lin_wan` 的排期一致。
