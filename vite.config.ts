/**
 * Copyright (c) 2025 Cade Russell
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;

// https://vite.dev/config/
export default defineConfig(async () => ({
  plugins: [react()],

  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },

  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 1421,
    strictPort: true,
    allowedHosts: [process.env.VITE_ALLOWED_HOSTS || "localhost"],
    // Bind to all interfaces (dual-stack `::` accepts both IPv4 127.0.0.1 and
    // IPv6 ::1), so http://localhost:1421 and http://127.0.0.1:1421 both work.
    // Tauri sets TAURI_DEV_HOST, which takes precedence as before.
    host: host || "::",
    hmr: host
      ? {
        protocol: "ws",
        host,
        port: 1421,
      }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
    // Proxy API requests to backend server
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
        secure: false,
        ws: true, // proxy WebSocket upgrades (terminal sessions)
      },
      // Analysis dashboards render in an iframe whose origin is this dev server
      // (API_BASE_URL is same-origin), and the backend rewrites Plotly's CDN URL
      // to the relative path /static/plotly.min.js. Without this proxy that
      // request hits Vite's SPA fallback and returns index.html (text/html) —
      // the browser then fails to execute it and every chart silently vanishes
      // while the static KPI numbers stay visible.
      '/static': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
        secure: false,
      },
    },
  },
  // `npm run preview` serves the BUILT bundle (dist/) instead of transforming
  // modules on demand. Load time is the difference between one bundle and
  // hundreds of separate requests, which is what makes the dev server feel slow
  // — badly so on WSL, where every file read crosses the filesystem boundary.
  // Requires `npm run build` first, and re-running it after a pull that touches
  // the frontend.
  //
  // It needs the same two proxies as `server` above, /static included: the
  // backend rewrites Plotly's CDN URL to /static/plotly.min.js, and without that
  // proxy the request falls through to the SPA entry and returns HTML, so every
  // analysis chart silently disappears while its KPI numbers stay correct.
  preview: {
    port: 1421,
    strictPort: true,
    allowedHosts: [process.env.VITE_ALLOWED_HOSTS || "localhost"],
    host: "::",
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
        secure: false,
        ws: true,
      },
      '/static': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
        secure: false,
      },
    },
  },
}));
