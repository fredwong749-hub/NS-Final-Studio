// UIRSI 排版客观分（RUBRIC R14–R17），由 shoot.mjs 产出的 <prefix>_audit.json 计算。
// 用法：node score.mjs r7 [r5 …]  → 每个前缀一行分数（0–10，一位小数）
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const clamp = (x) => Math.max(0, Math.min(10, Math.round(x * 10) / 10));
export function score(sum, shots) {
  const t = Math.max(1, sum.textEls);
  return {
    R14_字号与深度: clamp(10 * (1 - sum.fontOff / t) - Math.min(3, sum.shadowOff / shots)),
    R15_换行与截断: clamp(10 - (2 * (sum.overflow + sum.clipNoTitle + sum.orphan)) / shots),
    R16_间距: clamp(10 * (1 - sum.spaceOff / t)),
    R17_颜色与对比: clamp(10 - (100 * (sum.contrastFail + sum.contrastSecFail + sum.colorOff)) / t),
  };
}
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  for (const p of process.argv.slice(2).filter((x) => !process.argv.includes("--tech"))) {
    const a = JSON.parse(readFileSync(join(HERE, `${p}_audit.json`), "utf8"));
    console.log(p, JSON.stringify({ shots: a.shots.length, ...a.sum }), JSON.stringify(score(a.sum, a.shots.length)));
  }
}

/** 技术分（RUBRIC K1–K6），由 <prefix>_net.json（shoot.mjs）+ <prefix>_tasks.json（tasks.mjs）算 */
export function techScore(net, tasks) {
  const avgFirst = tasks.reduce((a, t) => a + (t.first_ms ?? 0), 0) / Math.max(1, tasks.length) / 1000;
  const pages = net.filter((x) => !/_light\./.test(x.file));
  // K2：首屏（主内容出来）之前发出的 /api 请求数，取各任务最大值；没有任务数据时退回“前 3 s”统计
  const fromTasks = tasks.map((t) => t.first_api).filter((x) => typeof x === "number");
  const maxFirst = fromTasks.length ? Math.max(...fromTasks) : Math.max(0, ...pages.map((x) => x.first3s));
  const slow = net.reduce((a, x) => a + x.slow.length, 0);
  const dup = net.reduce((a, x) => a + x.dup, 0);
  const big = net.reduce((a, x) => a + (x.bigImg ?? 0), 0);
  const imgKB = Math.max(0, ...net.map((x) => x.imgKB ?? 0));
  return {
    K1_首屏时间: clamp(10 - 3 * Math.max(0, avgFirst - 1.2)),
    K2_首屏请求数: clamp(10 - 0.5 * Math.max(0, maxFirst - 12)),
    K3_慢请求: clamp(10 - (2 * slow) / Math.max(1, net.length) * 5),
    K4_重复请求: clamp(10 - dup / Math.max(1, net.length)),
    K5_图片体积: clamp(10 - big / Math.max(1, net.length) - Math.max(0, imgKB - 3000) / 1000),
    _raw: { avgFirst: Math.round(avgFirst * 100) / 100, maxFirst, slow, dup, big, maxImgKB: imgKB },
  };
}
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1] && process.argv.includes("--tech")) {
  const [n, t] = process.argv.slice(2).filter((x) => x !== "--tech");
  const net = JSON.parse(readFileSync(join(HERE, `${n}_net.json`), "utf8"));
  const tasks = JSON.parse(readFileSync(join(HERE, `${t}_tasks.json`), "utf8")).tasks;
  console.log(JSON.stringify(techScore(net, tasks)));
}
