// UIPIXEL：操作记录（#/audit）的人话化。审计日志内容一个字段都不丢：表格里显示人话，原始接口路径 / 参数原值放在 title 和“技术详情”里。
// 场景名走 v3/sceneLabel.ts；角色名来自 /api/character-hub（cid → name）；镜头写“第N集 SN”；版本文件写“首帧 #n / 首帧（未登记）”。
import { useEffect, useState } from "react";
import { sceneLabel } from "./sceneLabel";
import { onLive } from "./live";

let cast: Map<string, string> | null = null;
let castP: Promise<void> | null = null;
let castOk = false;
let retryT: number | null = null;
const subs = new Set<() => void>();
// UIAUDIT P2：:8800 重启时打开这页，人名表取不到会一直显示“某个角色”。取失败（或拿到空表）就 15 秒后再取，
// 实时通道重连（hello）时也立刻再取；取到后所有用到的地方重渲染。
function loadCast(): Promise<void> {
  if (retryT != null) return Promise.resolve();
  if (!castP)
    castP = fetch("/api/character-hub")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d: { characters?: { cid: string; name: string }[] }) => {
        const m = new Map((d.characters ?? []).map((c) => [c.cid, c.name]));
        if (!m.size) throw new Error("empty");
        cast = m;
        castOk = true;
      })
      .catch(() => {
        cast = cast ?? new Map();
        castP = null; // 允许重取
        if (retryT == null && subs.size) retryT = window.setTimeout(() => ((retryT = null), void loadCast()), 15000);
      })
      .then(() => subs.forEach((f) => f()));
  return castP ?? Promise.resolve();
}
let liveHooked = false;
function hookLive() {
  if (liveHooked) return;
  liveHooked = true;
  onLive((e) => {
    if (e.type === "hello" && !castOk) { if (retryT != null) { window.clearTimeout(retryT); retryT = null; } void loadCast(); }
  });
}
/** 组件里用：角色名表到了会重渲染 */
export function useAuditNames() {
  const [, tick] = useState(0);
  useEffect(() => {
    const f = () => tick((x) => x + 1);
    subs.add(f);
    hookLive();
    if (!castOk) void loadCast();
    return () => void subs.delete(f);
  }, []);
}

const STAGE: Record<string, string> = { image: "首帧", first: "首帧", last: "尾帧", video: "视频" };
/** ep01-S3 → 第 1 集 S3 */
export const shotName = (s: string) => {
  const m = /^ep(\d+)-S(\d+)$/i.exec(s);
  return m ? `第 ${+m[1]} 集 S${+m[2]}` : s;
};
const charName = (cid: string) => cast?.get(cid) ?? cast?.get(cid.replace(/^ch_/, "")) ?? cast?.get(`ch_${cid}`) ?? (cid === "narrator" ? "旁白" : null);

/** 一个原始值（id / 路径 / 文件名）→ 人话；认不出来返回 null（调用方显示原值） */
export function humanValue(v: string): string | null {
  const s = v.trim();
  // take:ep01-S1/image/3、ep01-S1/image/3（回收站 take id）
  let m = /^(?:take:)?(ep\d+-S\d+)\/(image|last|video)\/(\d+)$/.exec(s);
  if (m) return `${shotName(m[1])} · ${STAGE[m[2]]} #${m[3]}`;
  // file:data/…/ep01-S1_s20261201.png#ep01-S1（还没登记成版本的图）
  m = /^file:.*?(ep\d+-S\d+)[^/]*\.(png|jpe?g|webp|mp4)(?:#(ep\d+-S\d+))?$/i.exec(s);
  if (m) return `${shotName(m[3] ?? m[1])} · ${/\/last|_last/.test(s) ? "尾帧" : /\.mp4$/i.test(s) ? "视频" : "首帧"}（还没登记的图）`;
  m = /^(ep\d+-S\d+)$/i.exec(s);
  if (m) return shotName(m[1]);
  // 单品挑选 pick:item:<cid>:<槽位>（UM-0924…）、v2 选角 v2cast-<id>
  m = /^pick:(?:item|sheet):([a-z0-9_]+):/i.exec(s);
  if (m) return `${charName(m[1]) ?? "角色"}的设定 / 单品（挑图）`;
  m = /^v2cast-(.+)$/.exec(s);
  if (m) return humanValue(m[1]) ?? "选角设置";
  // 场景 sk_xxx（可能带路径）
  if (/(^|\/)sk_[a-z0-9_]+/.test(s)) return `场景「${sceneLabel(s)}」`;
  // 单品 am-<cid>-xxxx / lw-<类>-xxx
  m = /^am-([a-z_]+?)-[0-9a-f]{6,}$/.exec(s);
  if (m) return `${charName(m[1]) ?? "角色"}的一件单品`;
  if (/^lw-[a-z]+-/.test(s)) return `${charName("lin_wan") ?? "林晚"}的一件单品`;
  // 角色 cid
  const cn = charName(s);
  if (cn) return cn;
  // 其他文件路径：只留文件“是什么”
  if (/[/\\]|\.(png|jpe?g|webp|json|mp4|wav|mp3|yaml|md)$/i.test(s)) return "一个文件（路径见技术详情）";
  return null;
}

const KEY: Record<string, string> = { id: "对象", stage: "阶段", look: "造型", gate: "闸门", episodes: "集", episode: "集", shot: "镜头", n: "版本", reason: "原因" };
const VAL: Record<string, Record<string, string>> = {
  stage: STAGE,
  gate: { look: "造型确认", script: "剧本确认", import: "导入确认", cut: "成片确认" },
};
/** 参数对象 → 一行人话（原值另给） */
export function humanObj(obj: Record<string, unknown> | undefined): { text: string; raw: string } {
  if (!obj) return { text: "", raw: "" };
  const raw = Object.entries(obj).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join(" · ");
  const text = Object.entries(obj)
    .map(([k, v]) => {
      const sv = typeof v === "string" ? v : typeof v === "number" ? String(v) : JSON.stringify(v);
      const hv = VAL[k]?.[sv] ?? (k === "episodes" || k === "episode" ? `第 ${sv} 集` : k === "look" ? `造型 ${sv}` : humanValue(sv) ?? sv);
      return `${KEY[k] ?? k}：${hv}`;
    })
    .join(" · ");
  return { text, raw };
}

/** 接口路径 → 做了什么 · 对哪个（认不出来的段落原样保留在 title / 技术详情） */
export function humanPath(path: string): string | null {
  const p = path.replace(/^\/api\//, "");
  const seg = p.split("/");
  const rules: [RegExp, (m: RegExpExecArray) => string][] = [
    [/^voices\/preview$/, () => "试听音色"],
    [/^voices\/([^/]+)\/pick$/, (m) => `选定音色 · ${charName(m[1]) ?? "某个角色"}`],
    [/^voices\/([^/]+)\/proposals$/, (m) => `提议修改音色 · ${charName(m[1]) ?? "某个角色"}`],
    [/^character-hub\/([^/]+)\/items\/([^/]+)\/primary$/, (m) => `设为主图 · ${charName(m[1]) ?? "某个角色"}的单品`],
    [/^character-hub\/([^/]+)\/items\/([^/]+)\/adopt$/, (m) => `采用单品 · ${charName(m[1]) ?? "某个角色"}`],
    [/^character-hub\/([^/]+)\/map$/, (m) => `挂造型 · ${charName(m[1]) ?? "某个角色"}`],
    [/^looks\/wardrobe\/items\/([^/]+)\/images$/, (m) => `上传单品图 · ${humanValue(m[1]) ?? "一件单品"}`],
    [/^looks\/wardrobe\/items$/, () => "新建单品"],
    [/^shots\/([^/]+)\/frame-jobs$/, (m) => `出图 · ${shotName(m[1])}`],
    [/^shots\/([^/]+)\/video-jobs$/, (m) => `出视频 · ${shotName(m[1])}`],
    [/^shots\/([^/]+)\/review$/, (m) => `审片 · ${shotName(m[1])}`],
    [/^trash\/object$/, () => "移到回收站"],
    [/^trash\/([^/]+)\/restore$/, () => "从回收站还原"],
    [/^assets\/scenes\/([^/]+)\/plate-pick$/, (m) => `选场景底图 · 场景「${sceneLabel(m[1])}」`],
    [/^assets\/(sk_[^/]+)\/refs$/, (m) => `改参考图 · 场景「${sceneLabel(m[1])}」`],
    [/^asset-rejects$/, () => "退回资产"],
    [/^edits$/, () => "提修改意见"],
    // UIPIXEL（UIAUDIT P2：27% 显示“其他操作”）——按 /api/audit 出现次数从高到低补
    [/^qwen\/tasks$/, () => "交给写作模型一个任务"],
    [/^qwen\/tasks\/([^/]+)\/script\/import$/, () => "导入写作模型写好的剧本"],
    [/^projects\/([^/]+)\/script$/, () => "保存剧本"],
    [/^projects$/, () => "新建项目"],
    [/^projects\/([^/]+)\/create$/, () => "创建项目"],
    [/^projects\/([^/]+)\/settings$/, () => "改项目设置"],
    [/^projects\/([^/]+)\/style\/confirm$/, () => "确认画风"],
    [/^projects\/([^/]+)\/style$/, () => "改画风"],
    [/^projects\/([^/]+)\/characters\/([^/]+)\/confirm$/, () => "确认角色"],
    [/^projects\/([^/]+)\/characters\/([^/]+)\/references$/, () => "上传角色参考图"],
    [/^projects\/([^/]+)\/characters\/([^/]+)$/, () => "改角色资料"],
    [/^shots\/([^/]+)\/takes\/(first|last|image|video)\/(\d+)\/(final|lock)$/, (m) => `定稿 · ${shotName(m[1])} ${STAGE[m[2]] ?? m[2]} #${m[3]}`],
    [/^shots\/([^/]+)\/first-frame$/, (m) => `设首帧 · ${shotName(m[1])}`],
    [/^shots\/([^/]+)\/gpu\d*-rerender$/, (m) => `请远端卡重出 · ${shotName(m[1])}`],
    [/^shots\/([^/]+)\/boost\/suggest$/, (m) => `让导演给改进建议 · ${shotName(m[1])}`],
    [/^shots\/([^/]+)\/audit-override$/, (m) => `改质检结论 · ${shotName(m[1])}`],
    [/^shots\/([^/]+)\/h\d+-override$/, (m) => `改分镜字段 · ${shotName(m[1])}`],
    [/^shots\/([^/]+)\/render$/, (m) => `出图 · ${shotName(m[1])}`],
    [/^script-chat\/sessions$/, () => "新开剧本对话"],
    [/^script-chat\/sessions\/([^/]+)\/chat$/, () => "剧本对话：发一句"],
    [/^script-chat\/sessions\/([^/]+)\/to-inbox$/, () => "剧本对话：存为导入候选"],
    [/^script-chat\/ab$/, () => "剧本两版对比"],
    [/^script-chat\/estimate$/, () => "估算写作花费"],
    [/^script-inbox\/validate$/, () => "校验剧本格式"],
    [/^script-input$/, () => "提交剧本原文"],
    [/^script-ab\/choice$/, () => "剧本两版里选一版"],
    [/^render\/image-presets$/, () => "新建出图预设"],
    [/^render\/image-presets\/([^/]+)$/, () => "删除出图预设"],
    [/^render\/endpoints\/(video|image)$/, (m) => `改${m[1] === "video" ? "出视频" : "出图"}服务地址`],
    [/^jobs\/([^/]+)\/cancel$/, () => "取消任务"],
    [/^llm\/providers\/([^/]+)\/test$/, (m) => `测试模型服务 · ${m[1]}`],
    [/^llm\/providers\/([^/]+)$/, (m) => `改模型服务 · ${m[1]}`],
    [/^llm\/purposes\/([^/]+)$/, () => "改某个用途用哪个模型"],
    [/^gpu\d*\/episodes\/(\d+)\/run$/, (m) => `远端卡整集出片 · 第 ${m[1]} 集`],
    [/^episodes\/(\d+)\/edit$/, (m) => `改本集设置 · 第 ${m[1]} 集`],
    [/^episodes\/(\d+)\/produce\/cancel$/, (m) => `取消整集出片 · 第 ${m[1]} 集`],
    [/^episodes\/(\d+)\/produce$/, (m) => `整集出片 · 第 ${m[1]} 集`],
    [/^edits\/([^/]+)\/adopt$/, () => "采用修改结果"],
    [/^assets\/characters\/([^/]+)\/import$/, (m) => `导入人物资产 · ${charName(m[1]) ?? "某个角色"}`],
    [/^character-hub\/([^/]+)\/wardrobe$/, (m) => `改衣橱 · ${charName(m[1]) ?? "某个角色"}`],
    [/^character-hub\/([^/]+)\/check-image$/, (m) => `检查人物图 · ${charName(m[1]) ?? "某个角色"}`],
    [/^projects\/([^/]+)\/production\/start$/, () => "开始自动制作"],
    [/^projects\/([^/]+)\/style\/color-reference$/, () => "上传色调参考图"],
    [/^looks\/wardrobe\/items\/([^/]+)$/, (m) => `改单品 · ${humanValue(m[1]) ?? "一件单品"}`],
  ];
  for (const [re, f] of rules) {
    const m = re.exec(p);
    if (m) return f(m);
  }
  void seg;
  return null;
}
