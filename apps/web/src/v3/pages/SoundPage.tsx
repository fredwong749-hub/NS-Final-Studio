// UIRSI（REDESIGN §3.6 / B4）：声音一级页 #/sound —— 角色音色 · 旁白 | 对白（按集）| 配乐
// 路由：#/sound?tab=voice|lines|bgm&ep=2&shot=ep02-S3（从画布某一镜点进来，对白滚到那一镜、配乐停在那一镜开头）
import { useEffect, useMemo, useState } from "react";
import { useStudio } from "../../store";
import { useHash } from "../../projects/route";
import { Empty, LoadError, Skel } from "../../ds";
import { VoiceStudio } from "../assets/VoiceStudio";
import { ShotLinesList } from "../sound/ShotLines";
import { BgmPlayer } from "../sound/BgmPlayer";
import { getEpisodeLines, getMusicList, type EpisodeLines, type Music } from "../sound/sound_api";
import "../sound/sound.css";

type Tab = "voice" | "lines" | "bgm";
const TABS: [Tab, string, string][] = [
  ["voice", "角色音色 · 旁白", "每个人物的声音，▶ 试听、换音色"],
  ["lines", "对白（按集）", "每一镜要说的话，逐句 ▶、整镜连播"],
  ["bgm", "配乐", "整集配乐波形，按镜头跳"],
];

function useQuery() {
  const h = useHash();
  return useMemo(() => new URLSearchParams(h.split("?")[1] ?? ""), [h]);
}
function setQuery(patch: Record<string, string | null>) {
  const [base, qs] = window.location.hash.split("?");
  const q = new URLSearchParams(qs ?? "");
  for (const [k, v] of Object.entries(patch)) (v == null ? q.delete(k) : q.set(k, v));
  const s = q.toString();
  window.history.replaceState(null, "", `${base || "#/sound"}${s ? `?${s}` : ""}`);
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

export default function SoundPage() {
  const q = useQuery();
  const studio = useStudio();
  const tab = (["voice", "lines", "bgm"].includes(q.get("tab") ?? "") ? q.get("tab") : "voice") as Tab;
  const shot = q.get("shot");
  const ep = Number(q.get("ep")) || Number(shot?.match(/^ep(\d+)/)?.[1]) || studio.episode?.number || 1;
  const eps = (studio.episodes ?? []).map((e) => ({ n: e.number, title: e.title }));
  return (
    <div className="v3p-page snd-page">
      <header className="v3p-head">
        <h1>♪ 声音</h1>
        <span className="v3p-muted">人物音色、旁白、每镜台词、整集配乐，都能直接听</span>
      </header>
      <nav className="v3p-tabs" role="tablist" aria-label="声音分类">
        {TABS.map(([k, label, hint]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} title={hint} onClick={() => setQuery({ tab: k })}>
            {label}
          </button>
        ))}
        {tab !== "voice" && eps.length > 0 && (
          <label className="snd-ep">
            <span className="v3p-muted">第</span>
            <select value={ep} onChange={(e) => setQuery({ ep: e.target.value, shot: null })} aria-label="选集">
              {eps.map((e) => (
                <option key={e.n} value={e.n}>
                  {e.n} 集{e.title ? ` · ${e.title}` : ""}
                </option>
              ))}
            </select>
          </label>
        )}
      </nav>
      {tab === "voice" && <VoiceStudio />}
      {tab === "lines" && <EpisodeLinesView ep={ep} shot={shot} />}
      {tab === "bgm" && <BgmView ep={ep} shot={shot} />}
    </div>
  );
}

function EpisodeLinesView({ ep, shot }: { ep: number; shot: string | null }) {
  const [d, setD] = useState<EpisodeLines | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [all, setAll] = useState(false);
  useEffect(() => {
    let alive = true;
    setD(null);
    setErr(null);
    getEpisodeLines(ep).then((x) => alive && setD(x), (e: Error) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, [ep, tick]);
  useEffect(() => {
    if (d && shot) document.getElementById(`snd-${shot}`)?.scrollIntoView({ block: "center" });
  }, [d, shot]);
  if (err) return <LoadError what="这一集的台词" err={err} retry={() => setTick((n) => n + 1)} />;
  if (!d) return <Skel h={320} />;
  const withLines = d.shots.filter((s) => s.lines.length);
  const shown = all ? d.shots : withLines;
  const n = withLines.reduce((a, s) => a + s.lines.length, 0);
  const local = withLines.reduce((a, s) => a + s.lines.filter((l) => l.play).length, 0);
  return (
    <section className="snd-ep-lines">
      <p className="v3p-muted">
        第 {d.episode} 集{d.title ? `《${d.title}》` : ""}：{withLines.length} 镜有台词，共 {n} 句，{local} 句现在就能听。
        {n > local && " 旁白用远端音色，合成成片后这里就能听。"}
        {d.shots.length > withLines.length && (
          <button type="button" className="v3p-link" onClick={() => setAll((v) => !v)}>
            {all ? "只看有台词的镜头" : `也显示没台词的 ${d.shots.length - withLines.length} 镜`}
          </button>
        )}
      </p>
      {!shown.length && <Empty icon="♪" title="这一集没有台词" />}
      {shown.map((s) => (
        <article key={s.shot} id={`snd-${s.shot}`} className={`snd-card${s.shot === shot ? " focus" : ""}`}>
          <header>
            <b>第 {s.index} 镜</b>
            <a className="v3p-link" href={`#${s.shot}`} title="回画布看这一镜">
              看画面
            </a>
            <a className="v3p-link" href={`#/sound?tab=bgm&ep=${ep}&shot=${s.shot}`} title="配乐里跳到这一镜">
              这一镜的配乐
            </a>
          </header>
          <ShotLinesList shot={s.shot} data={s} />
        </article>
      ))}
    </section>
  );
}

function BgmView({ ep, shot }: { ep: number; shot: string | null }) {
  const [list, setList] = useState<Music[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [openOld, setOpenOld] = useState(false);
  useEffect(() => {
    getMusicList().then((d) => setList(d.episodes), (e: Error) => setErr(e.message));
  }, [tick]);
  if (err) return <LoadError what="配乐" err={err} retry={() => setTick((n) => n + 1)} />;
  if (!list) return <Skel h={200} />;
  const m = list.find((x) => x.episode === ep);
  const fresh = m && !m.old_script ? m : null;
  const old = list.filter((x) => x.old_script);
  return (
    <section className="snd-bgm">
      {fresh ? (
        <BgmPlayer m={fresh} focusShot={shot} />
      ) : (
        <Empty icon="♪" title={`第 ${ep} 集还没有配乐`} sub="现在的剧本换过之后还没配乐；配好后这里自动出现，可以整集听、按镜头跳。" />
      )}
      {old.length > 0 && (
        <details className="snd-old" onToggle={(e) => setOpenOld((e.target as HTMLDetailsElement).open)}>
          <summary>以前剧本的配乐（{old.length} 集，和现在的剧本对不上，只供参考）</summary>
          {openOld && old.map((x) => (
            <BgmPlayer key={x.episode} m={x} focusShot={x.episode === ep ? shot : null} />
          ))}
        </details>
      )}
    </section>
  );
}
