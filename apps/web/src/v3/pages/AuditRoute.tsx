// 操作记录页（#/audit）：登录后每个写操作（谁 · 什么时候 · 做了什么 · 对哪个 · 结果）
import { AuditTable } from "../AuditDrawer";

export default function AuditRoute() {
  return (
    <div className="v3p-page">
      <h1 className="audit-h">操作记录</h1>
      <AuditTable />
    </div>
  );
}
