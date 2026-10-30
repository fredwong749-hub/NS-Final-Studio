import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./canvas-v2.css";
import "./canvas-v3.css";
import Root from "./projects/Root"; // T42：#/projects、#/inbox 走项目页，其余是原画布

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
