// T42 顶层路由：#/projects（项目）、#/projects/new 与 #/projects/<slug>/wizard/<step>（新建剧向导）、
// #/projects/<slug>/board（进度看板）、#/inbox（待办）。其余 hash 回到原画布。
import { useCallback, useEffect, useState } from "react";
import "../assets.css";
import "./projects.css";
import { ThemeToggle } from "../themeMode";
import { BoardView } from "./BoardView";
import { InboxView } from "./InboxView";
import { go, papi, type ProjectSummary } from "./papi";
import { lastCanvas, useHash } from "./route";
import { Wizard } from "./Wizard";

function useInboxCount() {
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    const load = () =>
      papi
        .inbox()
        .then((c) => alive && setN(c.length))
        .catch(() => {});
    load();
    const t = window.setInterval(load, 15000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);
  return n;
}

const STATUS_LABEL: Record<string, string> = { legacy: "现有项目", draft: "向导中", ready: "已创建" };

function ProjectList() {
  const [list, setList] = useState<ProjectSummary[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    papi.list().then(setList, (e: Error) => setErr(e.message));
  }, []);
  return (
    <div className="pj-page">
      <div className="pj-head">
        <h2>项目</h2>
        <span className="muted">每部剧一个项目目录（projects/&lt;代号&gt;/）；《为他而骚》仍在仓库根目录，作为默认项目。</span>
        <span className="grow" />
        <button className="btn primary big" onClick={() => go("#/projects/new")}>
          ＋ 新建剧
        </button>
      </div>
      {err && <div className="banner">{err}</div>}
      {!list && !err && <div className="empty">加载中…</div>}
      <div className="pj-grid">
        {list?.map((p) => (
          <div key={p.slug} className="pj-card">
            <div className="pj-card-top">
              <b className="pj-name">{p.name}</b>
              <span className={`chip ${p.status === "ready" ? "chip-ok" : p.status === "draft" ? "chip-warn" : "chip-accent"}`}>
                {STATUS_LABEL[p.status] ?? p.status}
              </span>
              {p.running && <span className="chip chip-busy">{p.mode === "dry_run" ? "演练中" : "生产中"}</span>}
            </div>
            <div className="muted small mono">{p.is_default ? "仓库根目录（slug weita）" : `projects/${p.slug}/`}</div>
            <div className="small">{p.episodes ? `${p.episodes} 集` : "未导入剧本"}</div>
            <div className="pj-card-actions">
              {p.status === "draft" && (
                <button className="btn" onClick={() => go(`#/projects/${p.slug}/wizard/script`)}>
                  继续向导
                </button>
              )}
              <button className="btn" onClick={() => go(`#/projects/${p.slug}/board`)}>
                进度看板
              </button>
              {p.is_default && (
                <button className="btn ghost" onClick={() => go("#/")}>
                  打开画布
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ProjectsApp() {
  const hash = useHash();
  const inbox = useInboxCount();
  const parts = hash.replace(/^#\//, "").split("/");
  let body;
  let tab = "projects";
  if (parts[0] === "inbox") {
    tab = "inbox";
    body = <InboxView />;
  } else if (parts[1] === "new") {
    body = <Wizard slug={null} step="name" />;
  } else if (parts[1] && parts[2] === "wizard") {
    body = <Wizard slug={decodeURIComponent(parts[1])} step={parts[3] || "script"} />;
  } else if (parts[1] && parts[2] === "board") {
    tab = "board";
    body = <BoardView slug={decodeURIComponent(parts[1])} />;
  } else {
    body = <ProjectList />;
  }
  const back = useCallback(() => go(lastCanvas()), []); // fredw-b3：回到离开时的那一镜
  return (
    <div className="app pj-app">
      <header className="topbar">
        <b className="brand">NS-Final Studio</b>
        <div className="seg">
          <button className={tab === "projects" ? "on" : ""} onClick={() => go("#/projects")}>
            项目
          </button>
          <button className={tab === "inbox" ? "on" : ""} onClick={() => go("#/inbox")}>
            待办{inbox > 0 && <span className="pj-count">{inbox}</span>}
          </button>
          {tab === "board" && <button className="on">进度看板</button>}
        </div>
        <span className="grow" />
        <ThemeToggle />
        <button className="btn-mini" onClick={back} title="回到《为他而骚》画布">
          ← 画布
        </button>
      </header>
      <main className="pj-main">{body}</main>
    </div>
  );
}
