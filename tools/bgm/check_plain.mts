// BGM10：给项目方看的配乐理由 / 提示的回归检查（UIAUDIT P2 v1、v2）。
//   1) 每集 chosen.reason_plain（审听模型改写，tools/bgm/plain.py）存在、没有内部用语 / 小数 / BPM / target / （r）、句子没有空位；
//   2) 每条候选的 flags_plain 同样干净；
//   3) 老记录回退 plainReason(原理由)：没有内部用语、没有空位（带空位的整句应已丢掉）；
//   4) 空位检测器本身：已知碎片要抓到，“是反的。”这类正常句尾不能误报。
// node --experimental-strip-types tools/bgm/check_plain.mts（退出码 1 = 有问题）
import { readFileSync } from "node:fs";
import { DANGLING, plainReason } from "../../apps/web/src/v3/sound/sound_api.ts";

const ROOT = new URL("../../", import.meta.url);
const FORBID =
  /[A-Za-z]+_[A-Za-z_]+|\b(?:energy|clap|vocal|tempo|gate|onset|centroid|brief|target|BPM|LUFS|dBTP|dB|Hz)\b|\d+\.\d+|闸门|[（(]\s*r?\s*[)）]|⁣/i;
// 回退里还要抓：“实测 完全跑飞”“与 的弱相关”“从 缓升至”这类删数后的碎片
const FRAG = /(?:实测|约|仅|从|至|与|和|为|是|在|达|到)\s+(?:的|完全|缓升|再|但|之外|边缘|[，。；、）)])/;
let bad = 0;
const fail = (what: string, s: string, why: string) => {
  bad++;
  console.log(`✘ ${what}：${why} → ${JSON.stringify(s)}`);
};
const clean = (what: string, s: string, needText = true, frag = false) => {
  if (needText && !s.trim()) return fail(what, s, "空");
  const f = s.match(FORBID);
  if (f) fail(what, s, `内部用语 / 小数 ${JSON.stringify(f[0])}`);
  const d = s.match(DANGLING);
  if (d) fail(what, s, `句子有空位 ${JSON.stringify(d[0])}`);
  const g = frag ? s.match(FRAG) : null;
  if (g) fail(what, s, `删数后的碎片 ${JSON.stringify(g[0])}`);
};

let fallbackEmpty = 0;
for (let e = 1; e <= 10; e++) {
  const ep = `ep${String(e).padStart(2, "0")}`;
  const st = JSON.parse(readFileSync(new URL(`data/music/series10/${ep}/meta.json`, ROOT), "utf8"));
  const ch = st.chosen ?? {};
  if (!ch.reason_plain) fail(`${ep} reason_plain`, "", "缺");
  else clean(`${ep} reason_plain`, ch.reason_plain);
  const fb = plainReason(ch.reason);
  if (!fb) fallbackEmpty++;
  clean(`${ep} 回退 plainReason`, fb, false, true);
  for (const c of st.candidates ?? []) {
    (c.flags ?? []).forEach((f: string, i: number) => {
      const fp = c.flags_plain?.[i];
      if (!fp) fail(`${ep} ${c.id} flags_plain[${i}]`, f, "缺");
      else clean(`${ep} ${c.id} flags_plain[${i}]`, fp);
      clean(`${ep} ${c.id} 回退 flag`, plainReason(f), false, true);
    });
  }
}

// 回退的单例：有空位的句子整句丢掉，干净的句子留下
const cases: [string, string][] = [
  ["clap 与最高值 0.3534 相当。没有人声。", "没有人声。"],
  ["r1_c2 的 107.7 是 60 的 1.8 倍，偏离更远。r1_c3 更好。", "r1_c3 更好。"],
  ["听感 clap 0.3634（r1_c1 仅 0.3123），乐器更像。速度对。", "速度对。"],
  ["(r=0.23)", ""],
  ["实测 64.6 BPM，接近 target 66。", "实测 64 拍/分，接近目标 66。"],
  ["energy_r=0.669 远高于其余（c4 0.381 / c3 -0.082）。", ""],
];
for (const [i, want] of cases) {
  const got = plainReason(i);
  if (got !== want) fail("回退单例", got, `输入 ${JSON.stringify(i)}，期望 ${JSON.stringify(want)}`);
}
// 空位检测器：要抓到的 / 不能误报的
for (const s of ["听感贴合度与最高值 相当", "r1_c2 的 是 60 的 倍", "（r1_c1 仅）", "最长空白 ，", "优于 r1_c1 的  之外"])
  if (!DANGLING.test(s)) fail("空位检测漏报", s, "应判为有空位");
for (const s of ["其余三条能量走向都是反的。", "速度每分钟约 68 拍，正合适。", "r1_c2 中段有两秒空档，铺底不够连续。"])
  if (DANGLING.test(s)) fail("空位检测误报", s, "正常句子");

console.log(`检查完：问题 ${bad}；老记录回退为空的理由 ${fallbackEmpty} 条（界面显示“理由见悬停原文”）`);
process.exitCode = bad ? 1 : 0;
