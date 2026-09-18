---
name: meeting-minutes
description: >-
  Structure raw meeting transcripts or notes into professional minutes with
  decisions, action items, owners, and deadlines. Use when the user provides
  a transcript, meeting notes, or asks to "take minutes", "summarize the
  meeting", or "extract action items".
tags: [meeting, minutes, action-items, decisions, transcript]
triggers:
  - "when user pastes a meeting transcript or notes"
  - "when user asks to take minutes or summarize a meeting"
  - "when user asks for action items or decisions from a discussion"
allowed-tools: [read_file, write_file, bash, python_execute]
author: LangConfig
---

# Meeting Minutes Skill

Turn a raw transcript / notes into structured, professional minutes.

## Output Structure

Produce minutes with exactly these sections:

1. **Meeting metadata** — date, attendees (inferred when available), duration
2. **Summary** — 2–4 sentences capturing what the meeting was about
3. **Decisions** — bullet list, one decision per item, past tense
4. **Action items** — bullet list with **owner** and **deadline** when
   inferable; format: `- [ ] **Owner**: task (deadline)`
5. **Open questions** — anything unresolved

## Rules

- **Never invent facts.** If a decision or owner is not in the transcript,
  mark it `(not stated in transcript)` rather than guessing.
- Preserve names as written; normalize obvious spelling variants only when
  the same person is clearly referenced (e.g. "Dr. Smith" / "Smith").
- When the user supplies a deadline convention ("EOW", "next sprint"),
  expand it once in the Action Items header, e.g. `(EOW = end of week)`.
- If the user asks for a file, write the minutes with the workspace
  `write_file` tool (markdown by default: `meeting_minutes.md`).

## Bundled script

`scripts/minutes.py` — deterministic formatter that converts a plain-text
transcript into draft minutes JSON (decisions + action items + open
questions). Use it for long transcripts (>1000 words) instead of parsing
manually. Invoke via `python_execute` or `bash`:

```bash
python /plugins/meeting-minutes/scripts/minutes.py < transcript.txt
```

Input: raw transcript on stdin. Output: JSON with `decisions`, `action_items`,
`open_questions`, `summary_hint` fields that you then turn into the final
minutes markdown.
