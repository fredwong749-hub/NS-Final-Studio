// NAVIA：Version 1 视频库（#/v1-library，只读）。L-125：V1 冻结为视频库；主导航只显示 V2，V1 只在这里看。
// 只有播放，没有“用这版 / 修改 / 重出”任何会改东西的入口；这里的文件不会被任何 V2 页面当参考或输入（L-126）。
import { useEffect, useState } from "react";
import "../navia.css";

type Lib = { run: string; label: string; readonly: boolean; frozen_at: string | null; total: number; episodes: { ep: number; shots: { id: string; index: number; n: number; video_url: string }[] }[] };

export default function V1Library() {
  const [d, setD] = useState<Lib | null>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<{ id: string; url: string } | null>(null);
  const load = () =>
    fetch("/api/v1-library")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((x: Lib) => (setD(x), setErr("")))
      .catch(() => setErr("视频库读不到，请稍后再点重试"));
  useEffect(() => void load(), []);
  return (
    <div className="vd-page">
      <div className="v1-banner" role="note">
        <b>Version 1 视频库</b>
        <span>只读 · 第一版（已冻结{d?.frozen_at ? ` ${d.frozen_at.slice(0, 16).replace("T", " ")}` : ""}）· 只能看，不能改；这里的图和视频不会进入 Version 2</span>
        <a className="v3-btn sm" href="#/videos" style={{ marginLeft: "auto" }}>
          回到 Version 2
        </a>
      </div>
      {err && !d && (
        <div className="vd-empty" role="alert">
          <b>{err}</b>
          <button className="v3-btn" onClick={() => void load()}>
            重试
          </button>
        </div>
      )}
      {!err && !d && <div className="vd-empty">正在读视频库…</div>}
      {d && d.total === 0 && (
        <div className="vd-empty">
          <b>视频库里没有可播放的视频</b>
          Version 1 的视频文件不在这台机器上。
        </div>
      )}
      {d?.episodes.map((e) => (
        <section key={e.ep}>
          <div className="vd-eph">
            <b>第 {e.ep} 集</b>
            <span>{e.shots.length} 条视频</span>
          </div>
          <div className="vd-grid">
            {e.shots.map((s) => (
              <button key={s.id} className="vd-shot" onClick={() => setOpen({ id: s.id, url: s.video_url })} title={`${s.id} · Version 1`}>
                <div className="im">
                  <video src={`${s.video_url}#t=0.4`} preload="metadata" muted playsInline />
                  <span className="id">
                    {e.ep}-S{s.index}
                  </span>
                </div>
                <div className="st">
                  <span>Version 1</span>
                  <span>只读</span>
                </div>
              </button>
            ))}
          </div>
        </section>
      ))}
      {open && (
        <aside className="vd-drawer" role="dialog" aria-label={`${open.id} Version 1 视频`}>
          <div className="row">
            <b>{open.id}</b>
            <span style={{ color: "var(--c-text-2,#aaa)" }}>Version 1 · 只读</span>
            <span style={{ flex: 1 }} />
            <button className="v3-btn sm" onClick={() => setOpen(null)}>
              关闭
            </button>
          </div>
          <video key={open.url} src={open.url} controls autoPlay loop muted playsInline />
        </aside>
      )}
    </div>
  );
}
