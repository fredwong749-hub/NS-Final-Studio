// 语法检查（vite 报错层就是语法 / 转换错）：用 vite 自己的 oxc 转换器转一遍。node syntax_check.mjs <文件> <tsx|ts>，退出 0 = 能转
import { readFileSync } from "node:fs";
import { transformWithOxc } from "vite";
const [, , f, lang = "tsx"] = process.argv;
try {
  const r = await transformWithOxc(readFileSync(f, "utf8"), `check.${lang}`, { lang, jsx: { runtime: "automatic" } });
  if (r.errors?.length) {
    console.log(r.errors.map((e) => e.message ?? String(e)).join("\n"));
    process.exit(1);
  }
  process.exit(0);
} catch (e) {
  console.log(String(e?.message ?? e).slice(0, 1500));
  process.exit(1);
}
