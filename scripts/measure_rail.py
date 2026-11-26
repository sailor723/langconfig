"""Measure the live rail geometry through Chrome DevTools Protocol.

The layout questions in this repo keep getting answered with arithmetic ("16 rows x 36px is
594px, so it fits") when the thing that actually matters is what the browser computed. This
script asks the browser: viewport height, device pixel ratio, the rail's scrollHeight vs
clientHeight (does it overflow?), and every child row's height and top offset.

Usage:  python measure_rail.py <url> [--auth user:pass]
Assumes a Chrome with --remote-debugging-port=9222 is already running on that URL.
"""
import asyncio
import base64
import json
import sys
import urllib.request

import websockets

PORT = 9222

EXPR = r"""
(() => {
  const rail = document.getElementById('lc-rail');
  const rect = rail ? rail.getBoundingClientRect() : null;
  const rows = rail ? [...rail.children].map(el => {
    const r = el.getBoundingClientRect();
    return {
      h: Math.round(r.height), top: Math.round(r.top), bottom: Math.round(r.bottom),
      cls: el.className || '', text: (el.textContent || '').trim().slice(0, 14),
    };
  }) : [];
  const lastVisible = rows.length ? rows[rows.length - 1].bottom : null;
  return JSON.stringify({
    url: location.href,
    innerH: window.innerHeight,
    dpr: window.devicePixelRatio,
    zoomScale: window.visualViewport ? window.visualViewport.scale : null,
    rail: rect ? {
      top: Math.round(rect.top), height: Math.round(rect.height),
      scrollH: rail.scrollHeight, clientH: rail.clientHeight,
      overflowY: getComputedStyle(rail).overflowY,
      overflows: rail.scrollHeight > rail.clientHeight,
    } : null,
    rows,
    lastRowBottom: lastVisible,
    doc: { scrollH: document.documentElement.scrollHeight, clientH: document.documentElement.clientHeight },
  });
})()
"""


async def main() -> None:
    url = sys.argv[1]
    auth = None
    if "--auth" in sys.argv:
        cred = sys.argv[sys.argv.index("--auth") + 1]
        auth = "Basic " + base64.b64encode(cred.encode()).decode()

    targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
    page = next(t for t in targets if t["type"] == "page")
    seq = 0

    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
        async def cmd(method, params=None):
            nonlocal seq
            seq += 1
            mine = seq
            await ws.send(json.dumps({"id": mine, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == mine:
                    if "error" in msg:
                        raise RuntimeError(msg["error"])
                    return msg.get("result", {})

        await cmd("Page.enable")
        await cmd("Runtime.enable")
        if auth:
            await cmd("Network.enable")
            await cmd("Network.setExtraHTTPHeaders", {"headers": {"Authorization": auth}})
        await cmd("Page.navigate", {"url": url})
        await asyncio.sleep(7)  # SPA boot + first data fetch
        res = await cmd("Runtime.evaluate", {"expression": EXPR, "returnByValue": True})
        value = res.get("result", {}).get("value")
        print(value if value else json.dumps(res)[:600])


asyncio.run(main())
