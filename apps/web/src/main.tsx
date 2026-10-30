import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./theme.css";
import { initTheme } from "./themeMode";
import "./styles.css";
import "./canvas-v2.css";
import "./canvas-v3.css";
import "./t59.css"; // T59
import "./ux-fix.css"; // fredw-b3 前端整理：最后加载
import Root from "./projects/Root"; // T42：#/projects、#/inbox 走项目页，其余是原画布

initTheme(); // T59：首帧渲染前定主题，避免闪烁

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
