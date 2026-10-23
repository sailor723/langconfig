/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

/**
 * Clipboard access from a non-secure origin.
 *
 * `navigator.clipboard` only exists in a *secure context*: https, localhost, or
 * a file. Opened over plain http from another machine — which is exactly what
 * LAN access looks like (`http://192.168.x.x:8765`, see
 * docs/reference/lan-access.md) — the whole object is `undefined`.
 *
 * The app calls `navigator.clipboard.writeText(...)` directly in ~20 places
 * (MessagesPanel, WorkflowCanvas, AgentContextViewer, the terminal, …). Each of
 * those throws `TypeError: Cannot read properties of undefined (reading
 * 'writeText')` on a LAN origin, so every copy button silently fails for the
 * second user. One file (features/knowledge/ui/DocChatPanel.tsx) already worked
 * around this locally for exactly that reason.
 *
 * Rather than patch twenty call sites — and miss the twenty-first that a future
 * change adds — install the fallback once at startup: if `clipboard` is
 * missing, define a minimal one backed by `document.execCommand('copy')`, the
 * pre-async-clipboard API, which has no secure-context requirement. Existing
 * call sites then keep working unchanged, and new code can prefer `copyText`
 * below, which reports whether the copy actually happened.
 */

/** Copy text, reporting success. Safe in a non-secure context. */
export async function copyText(text: string): Promise<boolean> {
  try {
    // `typeof` rather than a truthiness test: TypeScript types `clipboard` as
    // non-optional (it describes the secure-context case), so a plain check is
    // reported as "always true" — yet at runtime it is genuinely absent.
    if (typeof navigator.clipboard?.writeText === "function") {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Denied or unavailable — fall through to the legacy path.
  }
  return legacyCopy(text);
}

/** The pre-Clipboard-API path: needs no secure context and no permission. */
function legacyCopy(text: string): boolean {
  try {
    const area = document.createElement("textarea");
    area.value = text;
    // readonly keeps mobile keyboards from appearing; fixed + off-screen avoids
    // scrolling the page to the control we are about to select.
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "-1000px";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

/**
 * Give `navigator.clipboard` a stand-in when the context is insecure.
 *
 * Deliberately non-invasive: it never replaces a real implementation, and it
 * does nothing at all on https/localhost. Call once, before rendering.
 */
export function installClipboardFallback(): void {
  if (typeof navigator === "undefined") return;
  // Real implementation present (https / localhost): leave it untouched.
  if (typeof navigator.clipboard?.writeText === "function") return;

  const stub = {
    writeText: async (text: string): Promise<void> => {
      if (!legacyCopy(text)) {
        throw new Error("Clipboard unavailable in this browser context");
      }
    },
    // Reading the clipboard genuinely requires a secure context — there is no
    // legacy equivalent worth faking, so the call fails loudly instead of
    // returning an empty string that looks like an empty clipboard.
    readText: async (): Promise<string> => {
      throw new Error("Reading the clipboard requires HTTPS");
    },
  };

  try {
    Object.defineProperty(navigator, "clipboard", {
      value: stub,
      configurable: true,
      writable: true,
    });
  } catch {
    try {
      Object.defineProperty(Navigator.prototype, "clipboard", {
        get: () => stub,
        configurable: true,
      });
    } catch {
      // Give up quietly: copy buttons stay broken, but the app still runs.
    }
  }
}
