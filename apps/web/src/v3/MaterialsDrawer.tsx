// UX5（D2 / D3 W3、C 原则 21）：资料清单抽屉——顶栏 ①“剧本 · 资料”点进来就是本集“缺什么、谁来补、补完没有”。
// 数据和审片行“资料不全 N / 对不上 N”角标是同一个接口（GET /api/episodes/{ep}/readiness），口径一致。
// 按“缺的东西”归组（同一件事缺在 9 镜，就写一行 + 9 个镜头芯片），每组写谁补、给“去补”入口。只读，不改任何内容。
import { useEffect, useState } from "react";
import { useStudio } from "../store";
import { Button, Drawer, Empty, LoadError, Loading, Seg, Tag } from "../ds";
import { type EpMat, type Item } from "./Materials";
import { loadReadiness } from "./Materials.helpers";

type Group = { key: string; label: string; who: string; reasons: string[]; shots: string[] };
function groupBy(d: EpMat, kind: "missing" | "conflicts"): Group[] {
  const m = new Map<string, Group>();
  const add = (it: Item, shot: string | null) => {
    const g = m.get(it.key) ?? { key: it.key, label: it.label, who: it.who, reasons: [], shots: [] };
    if (shot) g.shots.push(shot);
    if (!g.reasons.includes(it.reason) && g.reasons.length < 4) g.reasons.push(it.reason);
    m.set(it.key, g);
  };
  if (kind === "missing") for (const it of d.episode_items) add(it, null);
  for (const s of d.shots) for (const it of s[kind]) add(it, s.id);
  return [...m.values()].sort((a, b) => b.shots.length - a.shots.length);
}

/** 谁补 → 去哪补（只给入口，不替人补） */
function fixLink(g: Group): { href: string; label: string } | null {
  if (/scene|plate|底图/i.test(g.key + g.label)) return { href: "#/assets?type=scene", label: "去资产 · 场景" };
  if (/identity|look|造型|身份|wardrobe|character/i.test(g.key + g.label) || g.who === "资产") return { href: "#/assets", label: "去资产中心" };
  if (/剧本|写作|script/.test(g.who)) return { href: "#/script-create", label: "去剧本" };
  return null;
}

export function MaterialsDrawerHost() {
  const st = useStudio();
  const [open, setOpen] = useState(false);
  const [d, setD] = useState<EpMat | null>(null);
  const [err, setErr] = useState(false);
  const [tab, setTab] = useState<"missing" | "conflicts">("missing");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const on = () => setOpen(true);
    window.addEventListener("ns:materials", on);
    return () => window.removeEventListener("ns:materials", on);
  }, []);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setD(null);
    setErr(false);
    loadReadiness(st.epNum, tick > 0).then((x) => alive && (x ? setD(x) : setErr(true)));
    return () => {
      alive = false;
    };
  }, [open, st.epNum, tick]);
  if (!open) return null;
  const miss = d ? groupBy(d, "missing") : [];
  const conf = d ? groupBy(d, "conflicts") : [];
  const ready = d ? d.shots.filter((s) => !s.missing.length).length : 0;
  const list = tab === "missing" ? miss : conf;
  return (
    <Drawer
      wide
      title={<>① 资料清单 · 第 {st.epNum} 集</>}
      onClose={() => setOpen(false)}
      foot={
        <>
          {/* UIRSI r4：剧本字段缺得多 = 让写作模型重写这一集（新建剧本 → 送导入），或去导入页换稿 */}
          <a className="ds-btn ghost sm" href="#/script-create" onClick={() => setOpen(false)} title="故事提纲 → 写作模型自动写到分镜 → 你确认导入">
            ＋ 新建剧本 ↗
          </a>
          <a className="ds-btn ghost sm" href="#/script-create?tab=import" onClick={() => setOpen(false)} title="换一份剧本稿：校验后由你确认导入">
            剧本导入 ↗
          </a>
          <span className="grow" />
          <Button size="sm" onClick={() => setTick((n) => n + 1)}>
            重新检查
          </Button>
          <Button onClick={() => setOpen(false)}>关闭</Button>
        </>
      }
    >
      {!d && !err && <Loading text="正在检查本集资料…" />}
      {err && <LoadError what="资料清单" err="GET /api/episodes/{ep}/readiness 没返回" retry={() => setTick((n) => n + 1)} />}
      {d && (
        <>
          <div className="mt-sum">
            <div className={ready === d.shots.length ? "ok" : ""}>
              <b>
                {ready}/{d.shots.length}
              </b>
              <span>镜资料齐（整集出片会出）</span>
            </div>
            <div className={miss.length ? "bad" : ""}>
              <b>{d.shots.length - ready}</b>
              <span>镜资料不全（整集出片跳过）</span>
            </div>
            <div className={conf.length ? "warn" : ""}>
              <b>{d.shots.filter((s) => s.conflicts.length).length}</b>
              <span>镜有对不上（只提示）</span>
            </div>
          </div>
          <div className="ds-row" style={{ margin: "12px 0" }}>
            <Seg
              value={tab}
              onChange={setTab}
              options={[
                ["missing", `缺资料 ${miss.length} 项`],
                ["conflicts", `对不上 ${conf.length} 项`],
              ]}
            />
            <span className="ds-muted ds-small">和审片行“资料不全 / 对不上”角标是同一份检查</span>
          </div>
          {!list.length && <Empty icon="✓" title={tab === "missing" ? "本集资料齐了" : "没有对不上的地方"} />}
          {list.map((g) => {
            const fx = fixLink(g);
            return (
              <section key={g.key} className={`mt-g ${tab === "missing" ? "bad" : "warn"}`}>
                <header>
                  <b>{g.label}</b>
                  <Tag tone={tab === "missing" ? "bad" : "warn"}>{g.shots.length ? `${g.shots.length} 镜` : "整集"}</Tag>
                  <span className="ds-muted ds-small">谁补：{g.who}</span>
                  <span className="ds-grow" />
                  {fx && (
                    <a className="ds-btn sm" href={fx.href} onClick={() => setOpen(false)}>
                      {fx.label} ›
                    </a>
                  )}
                </header>
                <ul>
                  {g.reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
                {g.shots.length > 0 && (
                  <div className="mt-shots">
                    {g.shots.map((s) => (
                      <a key={s} className="ac-shot" href={`#${s}`} onClick={() => setOpen(false)} title={`在画布打开 ${s}`}>
                        {s.split("-")[1]}
                      </a>
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </>
      )}
    </Drawer>
  );
}
