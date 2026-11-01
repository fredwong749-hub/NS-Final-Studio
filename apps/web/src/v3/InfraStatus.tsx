// UIRSI r38（项目方 22:1x：“uiux加个实时连接状态”）：顶栏一个连接状态胶囊，点开看明细；GPU 面板顶部同一块明细。
// 明细五样：跳板、笔记本到两台服务器的 6 条连接、两台服务器常驻是否在跑、笔记本本机两样、自动重连在做什么。
// 文案全是大白话（K-UI-037）；端口 / 地址只放在“技术细节”里。数据见 InfraStatus.helpers.ts。
import "./infra.css";
import { dotOf, useInfra, type InfraStatus } from "./InfraStatus.helpers";
import { Pop } from "./widgets";

/** 顶栏胶囊：一眼看到整体；点开看明细（复用 widgets.Pop：点外面 / Esc 关） */
export function InfraChip() {
  const { data, dead } = useInfra();
  if (dead) return null;
  const lv = data?.level ?? "unk";
  const bad = data ? data.tunnels.filter((t) => !t.ok).length : 0;
  // 顶栏挤：胶囊只写“连接 5/6”这种短字，整句放悬停和弹层
  const n = data?.tunnels.length ?? 0;
  // 全部正常时只留一个绿点（悬停有整句），省出顶栏位置给步骤条；有断的才写字
  // r39（总调度定 A）：断线时只写“0/6”这类短格式，整句在悬停和弹层里
  const label = !data ? "…" : !data.relay.ok ? "跳板断" : data.level === "ok" ? null : `${n - bad}/${n}`;
  return (
    <Pop
      className="infra-pop"
      btnClass={`infra-chip lv-${lv}`}
      align="right"
      title={data ? `连接状态：${data.summary}（${data.at} 更新）${data.dispatch ? `
派图：${data.dispatch.text}` : ""}；点开看每条连接` : "正在读连接状态"}
      label={
        <>
          <i className={`infra-dot ${lv}`} aria-hidden="true" />
          {label ?? <span className="infra-vh">连接正常</span>}
        </>
      }
    >
      {() => <InfraPanel d={data} />}
    </Pop>
  );
}

/** 明细（顶栏弹层和 GPU 面板顶部共用） */
export function InfraPanel({ d, compact = false }: { d: InfraStatus | null; compact?: boolean }) {
  if (!d) return <div className="infra-panel">正在读连接状态…</div>;
  const downAll = d.tunnels.length > 0 && d.tunnels.every((t) => !t.ok);
  return (
    <div className={`infra-panel lv-${d.level}${compact ? " compact" : ""}`} role="status" aria-live="polite">
      <div className="infra-sum">
        <i className={`infra-dot ${d.level}`} aria-hidden="true" />
        <b>{d.summary}</b>
        <small>{d.at} 更新</small>
      </div>
      {d.reconnect.length > 0 && (
        <ul className="infra-re">
          {d.reconnect.map((r) => (
            <li key={r}>↻ {r}</li>
          ))}
        </ul>
      )}
      {!compact && (
        <>
          {d.dispatch && (
            <div className="infra-row">
              <span className="infra-k">派图</span>
              <i className={`infra-dot ${d.dispatch.override ? "warn" : "ok"}`} aria-hidden="true" />
              <span>{d.dispatch.text}</span>
            </div>
          )}
          <div className="infra-row">
            <span className="infra-k">跳板</span>
            <i className={`infra-dot ${dotOf(d.relay.ok)}`} aria-hidden="true" />
            <span>{d.relay.text}</span>
            {d.relay.last_ok_at && <small>最近一次通：{d.relay.last_ok_at}</small>}
          </div>
          <div className="infra-row top">
            <span className="infra-k">到服务器</span>
            {downAll && !d.relay.ok ? (
              <span>6 条连接都断了（因为跳板断了）</span>
            ) : (
              <ul className="infra-tl">
                {d.tunnels.map((t) => (
                  <li key={t.port} title={t.tech}>
                    <i className={`infra-dot ${dotOf(t.ok)}`} aria-hidden="true" />
                    <b>{t.name}</b> {t.text}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="infra-row top">
            <span className="infra-k">服务器常驻</span>
            <ul className="infra-tl">
              {Object.entries(d.servers).map(([k, s]) => (
                <li key={k}>
                  <i className={`infra-dot ${dotOf(s.night_ok)}`} aria-hidden="true" />
                  <b>{s.name}</b> {s.text}
                </li>
              ))}
            </ul>
          </div>
          <div className="infra-row top">
            <span className="infra-k">笔记本本机</span>
            <ul className="infra-tl">
              {d.local.map((l) => (
                <li key={l.id} title={l.tech}>
                  <i className={`infra-dot ${dotOf(l.ok)}`} aria-hidden="true" />
                  <b>{l.label}</b> {l.text}
                </li>
              ))}
            </ul>
          </div>
          {!d.watchdog.ok && <div className="infra-row warn">自动重连的看门狗{d.watchdog.at ? `最后一次报到在 ${d.watchdog.at}` : "没有记录"}，可能没在运行</div>}
          <details className="infra-tech">
            <summary>技术细节</summary>
            <ul>
              {d.tunnels.map((t) => (
                <li key={t.port}>
                  {t.name}：{t.tech}，连续失败 {t.fails} 次{t.last_rebuild_at ? `，最近重建 ${t.last_rebuild_at}` : ""}
                </li>
              ))}
              {d.local.map((l) => (
                <li key={l.id}>
                  {l.label}：{l.tech}
                  {l.ms != null ? `，${l.ms} ms` : ""}
                </li>
              ))}
              <li>看门狗最后报到：{d.watchdog.at ?? "无"}；跳板最后一次检查：{d.relay.checked_at ?? "无"}</li>
            </ul>
          </details>
        </>
      )}
    </div>
  );
}
