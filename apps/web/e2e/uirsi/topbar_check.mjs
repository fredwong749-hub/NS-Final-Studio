// UIRSI r45 P0（项目方 04:4x：“我的猫猫车 logo 呢？还有剧本的那些选择呢？为什么顶部都没有了呀？”）：顶栏不回退检查。
// 每个主要页面、三种宽度都必须看得见：顶栏 .v3-top、momoso 标识（.v3-brand-full 或 .v3-brand-short 至少一个可见）、
// “＋ 新建剧本”入口 .v3-new、换集下拉（“第 N 集 ▾”）。
// W5b（A5 P2-1，按改版后的事实）：换集下拉不在顶栏里，在顶栏下面的范围条 .v3-scope 里；
//   范围条只出现在画布 #epNN、#/cut、#/videos、#/frames——这些页查“范围条里有第 N 集下拉”，其它页不查这一项。用 probe.mjs（无头 Chrome、只读、非 GET 全拦）逐页查。
// 用法：node apps/web/e2e/uirsi/topbar_check.mjs   → 打印逐页结果；有缺的退出码 1（G10 / iter_gate 可直接调用）
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PAGES = process.env.TOPBAR_PAGES ? process.env.TOPBAR_PAGES.split(",") : ["/#/overview", "/#ep01", "/#/script-create?new=1", "/#/assets?type=people", "/#/sound", "/#/cut", "/#/settings"];
const SIZES = ["1280x800", "1440x900", "1920x1080"];
const EXPR = `JSON.stringify((()=>{const vis=(e)=>{if(!e)return false;const r=e.getBoundingClientRect();const c=getComputedStyle(e);return r.width>0&&r.height>0&&c.visibility!=="hidden"&&c.display!=="none"&&r.bottom>0&&r.top<innerHeight};
const top=document.querySelector(".v3-top");
return {top:vis(top),brand:vis(document.querySelector(".v3-brand-full"))||vis(document.querySelector(".v3-brand-short")),
noOverlap:(()=>{const top=document.querySelector(".v3-top");if(!top)return false;const els=[...top.querySelectorAll(".v3-top-l > *, .v3-step, .v3-top-r > *")].filter((e)=>vis(e)&&!e.closest(".v3-top-hidden")&&!e.querySelector(".v3-step")&&!(e.matches(".v3-top-l > *, .v3-top-r > *")&&e.querySelector(".v3-top-l > *, .v3-top-r > *")));const R=els.map((e)=>e.getBoundingClientRect());for(let i=0;i<R.length;i++){if(R[i].left<-0.5||R[i].right>innerWidth+0.5)return false;for(let j=i+1;j<R.length;j++){if(els[i].contains(els[j])||els[j].contains(els[i]))continue;const a=R[i],b=R[j];if(a.left<b.right-1&&b.left<a.right-1&&a.top<b.bottom-1&&b.top<a.bottom-1)return false;}}return document.documentElement.scrollWidth<=innerWidth+1;})(),
newScript:vis(document.querySelector(".v3-new")),picker:(()=>{const h=location.hash;const need=!/^#\\//.test(h)||/^#\\/(cut|videos|frames)\\b/.test(h);if(!need)return true;return [...document.querySelectorAll(".v3-scope button")].some((b)=>/第\\s*\\d+\\s*集/.test(b.textContent)&&vis(b));})(),
navText:(()=>{const s=[...document.querySelectorAll(".v3-top .v3-step")];return s.length>0&&s.every((b)=>{const t=b.querySelector("span");return vis(b)&&t&&t.scrollWidth<=t.clientWidth+1&&b.scrollWidth<=b.clientWidth+1&&t.getBoundingClientRect().width>=t.textContent.trim().length*10;});})()}})())`;
// UIFIX-S：noOverlap = 顶栏各元素两两不重叠、不超出视口宽度、页面无横向滚动
// UIRSI2（总调度亲审 r47）：navText = 导航五步文字完整（span / 按钮不溢出、宽度放得下全部字，不许被挤成“1 剧 / 2 资”）
let bad = 0;
for (const p of PAGES)
  for (const s of SIZES) {
    let r;
    // 探针本身起不来（无头 Chrome 启动偶发失败）只重试一次；两次都起不来才记缺——这是工具问题，不掩盖顶栏回退
    for (let k = 0; k < 2; k++) {
      try {
        const out = execFileSync("node", [join(HERE, "probe.mjs"), p, EXPR, process.env.TOPBAR_WAIT || "12000", s], { encoding: "utf8", timeout: 120000, stdio: ["ignore", "pipe", "ignore"] }).trim().split("\n").pop();
        r = JSON.parse(JSON.parse(out));
        break;
      } catch (e) {
        r = { error: `探针没起来：${String(e.message || e).split("\n")[0].slice(0, 80)}` };
      }
    }
    const miss = r.error ? [r.error] : Object.entries(r).filter(([, v]) => !v).map(([k]) => k);
    if (miss.length) bad++;
    console.log(`${miss.length ? "✗" : "✓"} ${p} ${s}${miss.length ? " 缺：" + miss.join("、") : ""}`);
  }
console.log(bad ? `顶栏回退 ${bad} 处` : "顶栏齐全");
process.exit(bad ? 1 : 0);
