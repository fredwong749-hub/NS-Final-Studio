// 演示用前端（端口 5181），代码与 5173 同一份，只把 /api /files 代理到演示后端 8807
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const API = "http://127.0.0.1:8807";
export default defineConfig({
  root: "D:/NS-Final Studio/apps/web",
  plugins: [react()],
  cacheDir: "C:/Users/fredw/AppData/Local/Temp/claude/C--Users-fredw/760a7f62-839c-40af-8905-3d705ceeb3e1/scratchpad/live_demo/vite_cache",
  server: { host: "127.0.0.1", port: 5181, strictPort: true, proxy: { "/api": API, "/files": API } },
});
