import "./netDedupe"; // UIRSI r12：同一 GET /api 合并（W-02）
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./theme.css";
import { initTheme } from "./themeMode.helpers";
import "./styles.css";
import "./canvas-v2.css";
import "./canvas-v3.css";
import "./t59.css"; // T59
import "./ux-fix.css"; // fredw-b3 前端整理：最后加载
import { ZoomLayer } from "./ds/ZoomLayer"; // UIMASTER G11：全站小图点开看大图
import Root from "./projects/Root"; // T42：#/projects、#/inbox 走项目页，其余是原画布
import "./v3/ux4.css"; // UX4（第 4 轮 UX 迭代）：资产库左栏、换集进度、审片行视频主格等，放在 Root 之后，才能排在 v3.css 后面

import "./ds/ds.css"; // UX5 设计系统组件层：最后加载

initTheme(); // T59：首帧渲染前定主题，避免闪烁

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
    <ZoomLayer />
  </StrictMode>,
);
