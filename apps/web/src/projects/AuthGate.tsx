// 账户登录（项目方 2026-10-31：“系统是在我 login 的，意味着我所做的所有行为都是我个人行为，所以你不需要每个东西都要打上一个字”）。
// 没登录先登录；第一次用（还没有账户）就建项目方账户。登录后所有“需要你确认”的操作都是点一下即生效，身份来自登录。
// 后端还没有登录接口（旧 API）时照常进入，不挡路。
import { useEffect, useState, type ReactNode } from "react";
import { Brand } from "../ds/Brand";
import { Ctx, type Me } from "./AuthGate.helpers";

export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ me: Me; setup: boolean } | "loading" | "noauth">("loading");
  const load = () =>
    fetch("/api/auth/me")
      .then((r) => (r.status === 404 ? "noauth" : r.json()))
      .then((d) => setState(d === "noauth" ? "noauth" : { me: d.user, setup: d.setup_needed }))
      .catch(() => setState("noauth"));
  useEffect(() => {
    void load();
  }, []);
  const logout = () => void fetch("/api/auth/logout", { method: "POST" }).then(load);
  if (state === "loading") return <div className="boot">加载中…</div>;
  if (state === "noauth" || state.me) return <Ctx.Provider value={{ me: state === "noauth" ? null : state.me, logout }}>{children}</Ctx.Provider>;
  return <Login setup={state.setup} onDone={load} />;
}

function Login({ setup, onDone }: { setup: boolean; onDone: () => void }) {
  const [name, setName] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(setup ? "/api/auth/setup" : "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, password: pw }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`);
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="login">
      <form
        className="login-card"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Brand mode="full" size={30} />
        <h1>{setup ? "第一次使用：建你的账户" : "登录"}</h1>
        <p className="ds-muted ds-small">{setup ? "这个账户就是项目方。登录后你做的每个选择都记在你名下，不用再打字确认。" : "登录后，选图、通过、导入都是点一下即生效。"}</p>
        <label>
          <span>账户名</span>
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} autoComplete="username" />
        </label>
        <label>
          <span>密码</span>
          <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete={setup ? "new-password" : "current-password"} />
        </label>
        {err && <p className="login-err">{err}</p>}
        <button className="ds-btn primary wide" disabled={busy || !name.trim() || !pw} type="submit">
          {busy ? "…" : setup ? "建账户并进入" : "登录"}
        </button>
      </form>
    </div>
  );
}
