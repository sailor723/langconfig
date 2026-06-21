# Phase 8 — DeepAgent Studio (Read-only Visualizer)

> Visualize any DeepAgent's structure — Main Agent at center, Sub-agents around, Capabilities attached, real-time execution highlights.
> **Read-only**, no drag-and-drop, no editing. Pure visualization + debugging.

---

## 🎯 Goal (2 days)

| | Before Phase 8 | After Phase 8 |
|---|---|---|
| View DeepAgent structure | Read JSON in DB or guess from agent name | See visual graph (Main + Sub-agents + Skills/Tools/Prompt) |
| Debug skill routing | Read logs after the fact | Watch Skill Router pick a sub-agent in real-time |
| Edit config | Use DeepAgentBuilder form | (unchanged — Studio is read-only) |

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Header:  [Agent Picker ▾]      [▶ Test]  [⚙ Edit]            │
├────────────────┬────────────────────────────────┬──────────────┤
│ LEFT           │  CENTER CANVAS                 │  RIGHT       │
│ Capabilities   │  (ReactFlow, auto-layout)     │  Detail      │
│                │                                │  Panel       │
│ 🔧 Tools (8)   │       ┌────────────┐           │              │
│ 🧠 Memory      │       │ TodoList   │           │  (selected   │
│ 📂 Sandbox     │       └─────┬──────┘           │   node)      │
│ 🧭 Router LLM  │             ▼                  │              │
│                │    ┌─────────────────┐         │              │
│ (auto-assigned │    │  Main Agent     │         │              │
│  to Main)      │    │  deepseek-chat  │         │              │
│                │    └────────┬────────┘         │              │
│                │       ┌─────┼─────┐            │              │
│                │       ▼     ▼     ▼            │              │
│                │    ┌────┐ ┌────┐ ┌────┐         │              │
│                │    │Sub │ │Sub │ │Sub │         │              │
│                │    │  A │ │  B │ │  C │         │              │
│                │    └─┬──┘ └─┬──┘ └─┬──┘         │              │
│                │      │SKILL │SKILL │SKILL        │              │
│                │      ▼      ▼      ▼            │              │
├────────────────┴────────────────────────────────┴──────────────┤
│  RealtimeExecutionPanel (bottom drawer)                        │
│  └─ token stream | tool calls | selected skill | cost         │
└────────────────────────────────────────────────────────────────┘
```

---

## 📦 Scope (2-day MVP)

### Day 1 — Static visualizer

| Hour | Task | File(s) | Status |
|---|---|---|---|
| 0.5h | Create folder + base page + route | `src/features/deepagent-studio/StudioPage.tsx` | ☐ |
| 1h   | Agent picker dropdown (load list from `/api/deepagents`) | `components/AgentPicker.tsx` | ☐ |
| 1h   | Build structure assembly: fetch agent + skills + tools → render-ready data | `hooks/useAgentStructure.ts` | ☐ |
| 1h   | MainAgentNode component (center, large, with model + prompt preview) | `nodes/MainAgentNode.tsx` | ☐ |
| 1h   | SubAgentNode component (smaller, circular, shows skill ID) | `nodes/SubAgentNode.tsx` | ☐ |
| 1h   | Auto-layout (main center + sub-agents in ring using dagre) | `utils/autoLayout.ts` | ☐ |
| 0.5h | CapabilityBar at bottom (Tools / Memory / Sandbox / Router LLM chips) | `components/CapabilityBar.tsx` | ☐ |
| 1h   | Right-side Detail Panel (read-only) | `components/DetailPanel.tsx` | ☐ |
| 1h   | Wire all into DeepAgentCanvas (ReactFlow wrapper, no controls except zoom/pan) | `DeepAgentCanvas.tsx` | ☐ |

**Day 1 deliverable**: User can pick a DeepAgent → see its full structure with main, sub-agents, capabilities, click any node → see details. No real-time yet.

### Day 2 — Real-time execution

| Hour | Task | File(s) | Status |
|---|---|---|---|
| 1h   | Skill Router panel (shows which skill will be picked, calls `/api/chat/start` to trigger routing) | `components/SkillRouterPanel.tsx` | ☐ |
| 1h   | Reuse `RealtimeExecutionPanel` — show streaming tokens + tool calls | (reuse existing) | ☐ |
| 1.5h | Node execution status: parse SSE events → highlight active sub-agent node (border color) | `hooks/useExecutionHighlight.ts`, update `SubAgentNode.tsx` | ☐ |
| 0.5h | Hook into existing `/api/chat/start` and `/api/chat/message` SSE stream | `hooks/useAgentStream.ts` | ☐ |
| 1h   | Polish: loading states, empty state (no agents), error handling, theme alignment | various | ☐ |
| 1h   | Manual test: pick `demo_analysis` → run query → verify node highlights | — | ☐ |
| 0.5h | Commit + push + update main README | `README.md` | ☐ |

**Day 2 deliverable**: User picks agent → clicks ▶ Test → sends query → Skill Router highlights picked sub-agent → tokens stream → tool calls appear → cost updates.

---

## 🧩 Reuse Strategy (cut 80% of work)

| Existing | Reuse in Studio |
|---|---|
| `WorkflowCanvas.tsx` patterns | ReactFlow setup, Background, MiniMap, zoom/pan |
| `CustomNode.tsx` | Execution status border-color logic |
| `RealtimeExecutionPanel.tsx` | Drop-in for streaming tokens + tool calls |
| `TotalCostPanel.tsx` | Floating cost tracker |
| `useWorkflowStream.ts` hook | SSE subscription pattern (refactor for DeepAgent endpoint) |
| `useNodeExecutionStatus.ts` | Status enum (idle/running/success/error) |
| `WorkflowToolbar.tsx` style | Header layout for Studio |
| Theme system (CSS vars) | All colors automatically match |

**Estimated code reuse**: ~60% of components are small adaptations, not greenfield.

---

## 🔌 Backend Touchpoints

| Endpoint | Status | Studio usage |
|---|---|---|
| `GET /api/deepagents` | ✅ exists | List all agents for picker |
| `GET /api/deepagents/{id}` | ✅ exists | Fetch single agent config |
| `GET /api/skills?skill_ids=[...]` | ✅ exists | Resolve skill details for sub-agents |
| `GET /api/tools` | ✅ exists | List tools for capability bar |
| `POST /api/chat/start` | ✅ exists | Start session for ▶ Test |
| SSE `/api/chat/message` | ✅ exists | Stream tokens + tool calls |

**No new backend endpoints required** — Phase 8 is pure frontend. (If we later need `/api/deepagents/{id}/structure` for stats, that's Phase 8.5.)

---

## 🎨 Visual Design Tokens

| Element | Style |
|---|---|
| Main Agent node | 240×140 rounded, primary border, 🤖 icon, large |
| Sub-agent node | 140×90 rounded, secondary border, skill ID badge |
| Selected node | green ring (`#10b981`) |
| Running node | blue pulsing border |
| Success node | green static border (briefly) |
| Error node | red border |
| Skill Router arrow | dashed animated line (Main → active Sub) |
| Capability chips | bottom row, color-coded per type |
| Background | `BackgroundVariant.Dots` (existing Studio style) |

---

## 🚫 Non-goals (intentionally out of scope)

| Excluded | Reason |
|---|---|
| Drag-and-drop editing | Use DeepAgentBuilder for edits; Studio is read-only |
| Add/delete nodes | Same |
| Save layout position | Always auto-layout from data |
| Multi-agent comparison view | Future phase |
| Cost-per-sub-agent breakdown | Future (needs backend stats) |
| Export diagram (PNG/SVG) | Trivial add later |

These can be Phase 8.5+ if there's demand.

---

## 📁 File Structure

```
phase8/
└── README.md                                          ← this file

src/features/deepagent-studio/
├── StudioPage.tsx                                     ← page entry (route)
├── DeepAgentCanvas.tsx                                ← ReactFlow wrapper
├── components/
│   ├── AgentPicker.tsx                                ← top dropdown
│   ├── CapabilityBar.tsx                              ← bottom capability chips
│   ├── DetailPanel.tsx                                ← right detail panel
│   └── SkillRouterPanel.tsx                           ← router highlight + start chat
├── nodes/
│   ├── MainAgentNode.tsx                              ← center node
│   ├── SubAgentNode.tsx                               ← sub-agent circle node
│   └── nodeTypes.ts                                   ← exported map for ReactFlow
├── hooks/
│   ├── useAgentStructure.ts                           ← assemble render data
│   ├── useAgentStream.ts                              ← SSE subscription
│   └── useExecutionHighlight.ts                       ← node status from events
└── utils/
    └── autoLayout.ts                                  ← dagre-based positioning

src/App.tsx                                            ← add /studio/deepagent route
src/components/layout/ModernHeader.tsx                ← add "Studio ▾" menu item

README.md                                              ← update Recent Commits + Phase 8 section
```

---

## ✅ Acceptance Criteria

- [ ] User navigates to `/studio/deepagent` (or via header menu)
- [ ] Page shows empty state with "Pick an agent to visualize"
- [ ] Agent picker lists all `deep_agent_templates`
- [ ] Selecting an agent renders the visual graph within 1s
- [ ] Main Agent is centered; sub-agents are in a ring around it
- [ ] Capability chips show tools/memory/sandbox/router
- [ ] Click any node → right panel shows details (read-only)
- [ ] Click ▶ Test → chat session starts, Skill Router picks a sub-agent
- [ ] Selected sub-agent node pulses/highlights during execution
- [ ] Token stream appears in bottom panel
- [ ] Tool calls appear in bottom panel
- [ ] Cost updates in real-time
- [ ] Page works with `demo_analysis` agent (ID=56) without setup

---

## 🎯 Risk Mitigation

| Risk | Mitigation |
|---|---|
| Skill Router not returning fast enough | Fallback: highlight ALL sub-agents briefly, then narrow to picked |
| SSE events don't include `skill_name` (already do — Phase 6 added it) | Verify during Day 2 hour 1; if missing, fall back to `tool_name == "task"` + `args.subagent_type` |
| Auto-layout looks bad for many sub-agents (>8) | Cap ring at 8, switch to grid for more |
| Main Agent has no skills (empty sub-agents) | Show empty state in canvas area: "No sub-agents — add skills to this agent" |
| Backend API slow on first load | Show skeleton/spinner during fetch |

---

## 📊 Effort Summary

| Item | Estimate |
|---|---|
| **Total working time** | **~16 hours over 2 days** |
| Code (new) | ~800 lines (Studio-specific) |
| Code (reuse) | ~400 lines (cut/paste from existing Studio) |
| Backend changes | **0** |
| Tests | Manual smoke test (1 agent end-to-end) |
| Documentation | This README + main README update |

---

## 🚀 Why This Is The Right MVP

1. **Highest value-to-effort ratio** of any Phase 8 option
2. **No backend changes** = zero risk of breaking existing flows
3. **Reuses 60%+ of Studio** = familiar patterns, fast to build
4. **Skill Router visualization** = unique differentiator (LangGraph Studio has nothing equivalent)
5. **Read-only** = no new bugs from drag-drop interaction states
6. **Foundation for future** = future "edit in studio", "multi-agent view", "cost breakdown" all build on this

---

## 📅 Suggested Schedule

```
Day 1 (8h):
  09:00 — Set up + Agent Picker
  11:00 — Structure assembly hook
  13:00 — MainAgentNode + SubAgentNode
  15:00 — Auto-layout + DeepAgentCanvas wiring
  17:00 — DetailPanel + CapabilityBar
  18:00 — Commit Day 1 milestone

Day 2 (8h):
  09:00 — SkillRouterPanel + start chat integration
  11:00 — Execution highlight on sub-agents
  13:00 — Reuse RealtimeExecutionPanel + cost
  15:00 — Polish: loading, empty, error, theme
  16:00 — Manual test with demo_analysis
  17:00 — Commit + update main README
  18:00 — Done
```

---

## 📝 Open Questions (decide before Day 1)

1. **Route**: `/studio/deepagent` or `/deepagent-studio`? (suggest `/studio/deepagent`)
2. **Header entry**: Add to existing "Studio" tab as sub-menu, or new "DeepAgent Studio" top-level button? (suggest sub-menu under "Studio ▾")
3. **Edit button**: When clicked, where to navigate — `/studio/agents/edit/{id}` or open existing DeepAgentBuilder modal? (suggest open existing modal for consistency)