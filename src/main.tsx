/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import "./i18n";
import { applyServerLanguage, watchLanguageChanges } from "./i18n/applyServerLanguage";
import { installClipboardFallback } from "./lib/clipboard";

// Before the first render: a page opened over plain http from another machine
// (LAN access) is not a secure context, so `navigator.clipboard` does not exist
// and every copy button would throw. See src/lib/clipboard.ts.
installClipboardFallback();

// 界面语言以**全局设置**为准，其次才轮到 localStorage / 浏览器语言。
// 先取语言再渲染：否则第一屏是英文、下一帧才变中文（那正是"半个界面两种语言"的来源）。
void applyServerLanguage().finally(() => {
  watchLanguageChanges();
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
});
