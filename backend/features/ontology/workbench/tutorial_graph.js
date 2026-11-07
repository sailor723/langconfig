/* tutorial_graph.js — interactive objects/lineage graph for the tutorial.
   - wheel zoom (around the cursor), drag to pan, +/-/reset buttons
   - click a node: highlight it and its edges, caption below the graph
   - renders from /api/graph?step=N (nodes with x,y,w,h + edges with labels) */
(function () {
  const COLORS = {
    object: ["#eef3fb", "#0b4f9c"], class: ["#eef3fb", "#0b4f9c"],
    defined: ["#fdf6e3", "#8a6d3b"], action: ["#fbe9e7", "#b3261e"],
    store: ["#f2f4f6", "#687b8f"], prop: ["#f7f9fb", "#687b8f"],
  };
  const EDGE = { join: "#0b4f9c", sub: "#8a6d3b", def: "#8a6d3b", write: "#b3261e",
                 prop: "#9fb8cf", column: "#9fb8cf" };
  const NS = "http://www.w3.org/2000/svg";
  let state = { k: 1, tx: 0, ty: 0, sel: null };
  let last = { nodes: [], edges: [] };

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => e.setAttribute(k, v));
    if (parent) parent.appendChild(e);
    return e;
  }

  function applyTransform(svg, g) {
    g.setAttribute("transform", `translate(${state.tx} ${state.ty}) scale(${state.k})`);
  }

  function layout() {
    const { nodes, edges } = last;
    const rankOf = {};
    nodes.forEach(n => { rankOf[n.id] = 0; });
    for (let pass = 0; pass < nodes.length; pass++) {
      let changed = false;
      edges.forEach(e => {
        if (e.a === e.b || e.self) return;
        const r = (rankOf[e.a] || 0) + 1;
        if ((rankOf[e.b] || 0) < r) { rankOf[e.b] = r; changed = true; }
      });
      if (!changed) break;
    }
    const cols = {};
    nodes.forEach(n => {
      const r = rankOf[n.id] || 0;
      (cols[r] = cols[r] || []).push(n);
    });
    const COLW = 150, ROWH = 66, PAD = 18;
    Object.entries(cols).forEach(([r, list]) => {
      list.forEach((n, i) => {
        n.w = 120; n.h = 44;
        n.x = PAD + Number(r) * COLW;
        n.y = PAD + i * ROWH;
      });
    });
  }

  function edgePath(a, b) {
    if (a.id === b.id || a === b) {
      const x = a.x + a.w, y = a.y + a.h / 2;
      return { d: `M ${x} ${y} C ${x + 26} ${y}, ${x + 26} ${a.y + a.h + 18}, ${a.x + a.w / 2} ${a.y + a.h}`, tx: x + 30, ty: y - 6 };
    }
    const rightward = b.x >= a.x + a.w;
    if (rightward) {
      const x1 = a.x + a.w, y1 = a.y + a.h / 2;
      const x2 = b.x, y2 = b.y + b.h / 2;
      const dx = Math.max(30, (x2 - x1) * 0.45);
      return { d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
               tx: (x1 + x2) / 2, ty: (y1 + y2) / 2 - 5 };
    }
    // downward / same column: curve from bottom edge to top edge
    const x1 = a.x + a.w / 2, y1 = a.y + a.h;
    const x2 = b.x + b.w / 2, y2 = b.y;
    const dy = Math.max(20, (y2 - y1) * 0.5);
    return { d: `M ${x1} ${y1} C ${x1} ${y1 + dy}, ${x2} ${y2 - dy}, ${x2} ${y2}`,
             tx: (x1 + x2) / 2 + 6, ty: (y1 + y2) / 2 };
  }

  function draw(svg, wrap) {
    const { nodes, edges } = last;
    const pad = 20, maxX = Math.max(...nodes.map(n => n.x + n.w), 200),
           maxY = Math.max(...nodes.map(n => n.y + n.h), 120);
    const W = maxX + pad, H = maxY + pad;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "100%");
    svg.innerHTML = "";
    const g = el("g", {}, svg);
    const defs = el("defs", {}, svg);
    defs.innerHTML = '<marker id="ag" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" ' +
      'markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="#334e68"/></marker>';
    const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
    const edgeEls = [];
    edges.forEach(e => {
      const a = byId[e.a], b = byId[e.b];
      if (!a || !b) return;
      const p = edgePath(a, b);
      const line = el("path", {
        d: p.d, fill: "none", stroke: EDGE[e.k] || "#334e68", "stroke-width": "1.4",
        "stroke-linecap": "round", "stroke-linejoin": "round",
        "stroke-dasharray": e.k === "def" ? "4 3" : "0", "marker-end": "url(#ag)",
      }, g);
      const t = el("text", {
        x: p.tx, y: p.ty, "font-size": "9.5",
        fill: EDGE[e.k] || "#687b8f", "font-family": "ui-monospace,Menlo,monospace",
      }, g);
      t.textContent = e.l || "";
      edgeEls.push({ line, a: e.a, b: e.b });
    });
    const nodeEls = [];
    nodes.forEach(n => {
      const [fill, stroke] = COLORS[n.k] || COLORS.prop;
      const r = el("rect", {
        x: n.x, y: n.y, width: n.w, height: n.h, rx: 8, fill, stroke,
        "stroke-width": "1.4", "data-id": n.id,
      }, g);
      r.style.cursor = "pointer";
      const title = el("text", {
        x: n.x + 7, y: n.y + 13, "font-size": "8.5", "font-weight": "600", fill: stroke,
        "font-family": "ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif",
        "pointer-events": "none",
      }, g);
      title.textContent = n.t;
      (n.l || []).forEach((line, i) => {
        const lt = el("text", {
          x: n.x + 7, y: n.y + 24 + i * 9.5, "font-size": "7", fill: "#687b8f",
          "font-family": "ui-monospace,Menlo,monospace", "pointer-events": "none",
        }, g);
        lt.textContent = line;
      });
      nodeEls.push({ id: n.id, rect: r, node: n });
    });
    state.edgeEls = edgeEls;
    state.nodeEls = nodeEls;
    svg.addEventListener("click", (ev) => {
      if (window.__nodeDragged) { window.__nodeDragged = false; return; }
      const t = ev.target;
      if (t && t.tagName === "rect" && t.dataset.id) select(t.dataset.id);
    });
    applyTransform(svg, g);
    state.svg = svg; state.g = g; state.W = W; state.H = H;
    select(state.sel);
  }

  function select(id) {
    state.sel = id;
    const cap = document.getElementById("graph-caption");
    if (!id) { if (cap) cap.textContent = "click a node to inspect it"; return; }
    (state.nodeEls || []).forEach(ne => {
      const on = ne.id === id;
      ne.rect.setAttribute("stroke-width", on ? "3" : "1.4");
      ne.rect.setAttribute("fill-opacity", on ? "1" : "0.55");
    });
    (state.edgeEls || []).forEach(ee => {
      const on = ee.a === id || ee.b === id;
      ee.line.setAttribute("stroke-width", on ? "2.6" : "1");
      ee.line.setAttribute("opacity", on ? "1" : "0.25");
    });
    const n = (last.nodes || []).find(x => x.id === id);
    if (cap && n) cap.textContent = n.t + (n.l && n.l.length ? " — " + n.l.join(" · ") : "");
  }

  function userCoords(svg, ev) {
    const r = svg.getBoundingClientRect();
    const W = state.W || 1, H = state.H || 1;
    return { x: (ev.clientX - r.left) * (W / r.width),
             y: (ev.clientY - r.top) * (H / r.height) };
  }

  function wireZoom(svg, wrap) {
    // wheel zoom (no panning — drag is for moving SINGLE nodes, not the whole graph)
    svg.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const p = userCoords(svg, ev);
      const old = state.k;
      state.k = Math.min(4, Math.max(0.35, state.k * (ev.deltaY < 0 ? 1.15 : 1 / 1.15)));
      const f = state.k / old;
      state.tx = p.x - f * (p.x - state.tx);
      state.ty = p.y - f * (p.y - state.ty);
      applyTransform(svg, state.g);
    }, { passive: false });

    // node dragging: mousedown on a node rect moves THAT node (edges follow)
    let nodeDrag = null;
    svg.addEventListener("mousedown", (ev) => {
      const t = ev.target;
      if (!t || t.tagName !== "rect" || !t.dataset.id) return;
      ev.preventDefault();
      const p = userCoords(svg, ev);
      const n = (last.nodes || []).find(x => x.id === t.dataset.id);
      if (!n) return;
      nodeDrag = { id: n.id, dx: p.x - n.x, dy: p.y - n.y };
      window.__nodeDragged = false;
    });
    window.addEventListener("mousemove", (ev) => {
      if (!nodeDrag) return;
      const p = userCoords(svg, ev);
      const n = (last.nodes || []).find(x => x.id === nodeDrag.id);
      if (!n) return;
      if (Math.abs(p.x - nodeDrag.dx - n.x) + Math.abs(p.y - nodeDrag.dy - n.y) > 3) {
        window.__nodeDragged = true;
      }
      n.x = Math.round(p.x - nodeDrag.dx);
      n.y = Math.round(p.y - nodeDrag.dy);
      draw(svg, wrap);
    });
    window.addEventListener("mouseup", () => { nodeDrag = null; });
  }

  function makeToolbar(wrap) {
    const bar = document.createElement("div");
    bar.className = "graph-toolbar";
    bar.innerHTML = '<span class="gtitle">Objects &amp; lineage</span>' +
      '<span class="grow"></span>' +
      '<button data-z="out" title="zoom out">−</button>' +
      '<button data-z="in" title="zoom in">+</button>' +
      '<button data-z="reset" title="reset">⟲</button>';
    wrap.prepend(bar);
    bar.addEventListener("click", (ev) => {
      const z = ev.target.dataset && ev.target.dataset.z;
      if (!z) return;
      const svg = state.svg; if (!svg) return;
      if (z === "reset") { state.k = 1; state.tx = 0; state.ty = 0; }
      else state.k = Math.min(4, Math.max(0.35, state.k * (z === "in" ? 1.2 : 1 / 1.2)));
      applyTransform(svg, state.g);
    });
  }

  function render(step) {
    const wrap = document.getElementById("mini-graph");
    if (!wrap) return;
    wrap.innerHTML = '<div class="gwrap"></div>';
    const gwrap = wrap.querySelector(".gwrap");
    const svg = el("svg", {});
    gwrap.appendChild(svg);
    state = { k: 1, tx: 0, ty: 0, sel: null };
    fetch("/api/graph?step=" + step).then(r => r.json()).then(j => {
      if (!j.ok) { wrap.textContent = "graph unavailable"; return; }
      last = j;
      layout();
      makeToolbar(wrap);
      const cap = document.getElementById("graph-caption");
      if (cap) cap.textContent = "click a node to inspect it";
      draw(svg, wrap);
      wireZoom(svg, gwrap);
    }).catch(() => { wrap.textContent = "graph unavailable"; });
  }

  window.tutorialGraph = render;
  const div = document.getElementById("mini-graph");
  if (div) render(div.dataset.step || "1");
})();
