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
import { installClipboardFallback } from "./lib/clipboard";

// Before the first render: a page opened over plain http from another machine
// (LAN access) is not a secure context, so `navigator.clipboard` does not exist
// and every copy button would throw. See src/lib/clipboard.ts.
installClipboardFallback();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
