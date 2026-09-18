"""
Deck template registry + outline normalization for the doc → deck pipeline.

A *template* is the unit of output control the user asked for: a real
``.pptx`` base file (authored by ``scripts/build_deck_templates.py``) that
carries themed master layouts (cover / section / content / data / closing),
plus a JSON spec with palette, fonts, layout map and content constraints.

The pipeline keeps a strict separation:

    1. doc_to_slides_outline  — LLM turns a document into a 12–15 slide outline
    2. normalize_outline      — deterministic constraints (clamp / truncate /
                                auto-highlight), no LLM
    3. render HTML / PPTX     — pure function of (outline, template)

The LLM decides *what* (content, faithfulness, emphasis); the template decides
*how* (layout, colors, fonts, constraints); the renderer is a pure function.
That is what makes output reproducible and controllable in both formats.

Templates are data, not code: adding a new look later = drop in a ``.pptx``
template file + one spec block below.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Directory that holds the generated template .pptx files.
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "decks"

# ── Palettes (id → colors) ────────────────────────────────────────────────
# Single source of truth — presentation_tools.THEMES is re-exported from here
# so the renderers and the registry can never drift.
PALETTES: Dict[str, Dict[str, str]] = {
    "business": {
        "label": "Business / Corporate (navy + gold)",
        "primary": "#1A2A4A", "accent": "#C8A24A", "accent_light": "#D8BD77", "accent_dark": "#A8842F",
        "bg": "#EEF0F5", "card": "#FFFFFF", "card_line": "#E6E9F0", "body": "#4A5570", "muted": "#7A8398",
        "dark_bg": "#1A2A4A", "dark_text": "#DBE2EF", "font": "Calibri",
    },
    "fashion": {
        "label": "Fashion / Editorial (black + gold, serif)",
        "primary": "#0B0B0F", "accent": "#BFA05A", "accent_light": "#D6BC7E", "accent_dark": "#8F7738",
        "bg": "#F7F4EE", "card": "#FFFFFF", "card_line": "#E8E1D2", "body": "#2B2B2B", "muted": "#8A8A8A",
        "dark_bg": "#0B0B0F", "dark_text": "#F2EEE4", "font": "Georgia",
    },
    "tech": {
        "label": "Technology (slate + cyan)",
        "primary": "#0F172A", "accent": "#22D3EE", "accent_light": "#67E8F9", "accent_dark": "#0891B2",
        "bg": "#F1F5F9", "card": "#FFFFFF", "card_line": "#E2E8F0", "body": "#334155", "muted": "#64748B",
        "dark_bg": "#0F172A", "dark_text": "#E2E8F0", "font": "Segoe UI",
    },
    "health": {
        "label": "Healthcare (teal + white)",
        "primary": "#134E4A", "accent": "#14B8A6", "accent_light": "#5EEAD4", "accent_dark": "#0F766E",
        "bg": "#F0FDFA", "card": "#FFFFFF", "card_line": "#CCFBF1", "body": "#115E59", "muted": "#5F7A76",
        "dark_bg": "#134E4A", "dark_text": "#E6FFFA", "font": "Calibri",
    },
    "education": {
        "label": "Education (indigo + amber)",
        "primary": "#3730A3", "accent": "#F59E0B", "accent_light": "#FCD34D", "accent_dark": "#B45309",
        "bg": "#F8FAFC", "card": "#FFFFFF", "card_line": "#E2E8F0", "body": "#1E293B", "muted": "#64748B",
        "dark_bg": "#3730A3", "dark_text": "#EEF2FF", "font": "Calibri",
    },
    "minimal": {
        "label": "Minimal (monochrome)",
        "primary": "#111111", "accent": "#8A8A8A", "accent_light": "#B0B0B0", "accent_dark": "#555555",
        "bg": "#FFFFFF", "card": "#F5F5F5", "card_line": "#E0E0E0", "body": "#333333", "muted": "#999999",
        "dark_bg": "#111111", "dark_text": "#F5F5F5", "font": "Arial",
    },
}

# CJK-capable font used for East-Asian glyph runs (library-level theme font).
CJK_FONT = "Microsoft YaHei"

# python-pptx default-template layout indexes → slide kinds.
# 0 Title Slide (restyled dark cover) · 1 Title and Content · 2 Section Header
# 5 Title Only · 6 Blank · 7 Content with Caption
DEFAULT_LAYOUT_MAP: Dict[str, int] = {
    "title": 0,
    "agenda": 2,
    "section": 2,
    "content": 1,
    "data": 7,
    "timeline": 7,
    "quote": 5,
    "conclusion": 1,
    "closing": 0,
}

DEFAULT_CONSTRAINTS: Dict[str, Any] = {
    "pages_min": 12,
    "pages_max": 15,
    "bullets_min": 3,
    "bullets_max": 5,
    "bullet_max_chars": 90,
    "max_cards": 6,
    "card_max_chars": 48,
    "auto_highlight_numbers": True,
}

TEMPLATE_SPECS: Dict[str, Dict[str, Any]] = {
    tid: {
        "id": tid,
        "name": palette["label"],
        "description": (
            f"{palette['label']} deck — layouts: cover / agenda / content / "
            "data / conclusion / closing, 12–15 pages."
        ),
        "template_file": str(TEMPLATES_DIR / f"{tid}.pptx"),
        "palette": palette,
        "fonts": {"latin": palette.get("font", "Calibri"), "cjk": CJK_FONT},
        "layout_map": DEFAULT_LAYOUT_MAP,
        "constraints": DEFAULT_CONSTRAINTS,
    }
    for tid, palette in PALETTES.items()
}

# Allowed slide kinds; unknown kinds map to "content".
SLIDE_KINDS = {
    "title", "agenda", "section", "content", "data", "timeline", "quote",
    "conclusion", "closing",
}
DARK_KINDS = {"title", "closing"}

# A bullet that is *mostly* a number / percentage / delta reads as a KPI →
# rendered as a big accent card ("highlight").
_NUMBERISH_RE = re.compile(r"^[\d.,%+\-\u2192\u2190$€£\s/'\"]{2,}$")


def list_templates() -> List[Dict[str, Any]]:
    """Public template catalog: id / name / description / palette summary."""
    return [
        {
            "id": spec["id"],
            "name": spec["name"],
            "description": spec["description"],
            "palette": {k: v for k, v in spec["palette"].items() if k != "label"},
            "constraints": spec["constraints"],
            "has_template_file": Path(spec["template_file"]).exists(),
        }
        for spec in TEMPLATE_SPECS.values()
    ]


def get_template(template_id: str) -> Dict[str, Any]:
    """Resolve a template spec by id (case-insensitive)."""
    key = (template_id or "business").strip().lower()
    spec = TEMPLATE_SPECS.get(key)
    if spec is None:
        raise ValueError(
            f"Unknown template '{template_id}'. Choose one of: {', '.join(sorted(TEMPLATE_SPECS))}"
        )
    return spec


def get_palette(template_id: str) -> Dict[str, str]:
    """Palette dict for a template (color hex values + font)."""
    return get_template(template_id)["palette"]


# ── Outline normalization (deterministic control layer) ──────────────────

def _clamp_bullet(bullet: str, template: Dict[str, Any]) -> str:
    max_chars = template["constraints"]["bullet_max_chars"]
    b = str(bullet or "").strip()
    if len(b) > max_chars:
        b = b[: max_chars - 1].rstrip() + "…"
    return b


def _is_numberish(bullet: str) -> bool:
    return bool(_NUMBERISH_RE.match(bullet.strip()))


def normalize_outline(
    outline: Optional[Dict[str, Any]],
    template: Dict[str, Any],
    clamp_pages: bool = True,
) -> Tuple[Dict[str, Any], List[str]]:
    """Apply template constraints to a raw LLM outline. Deterministic, no LLM.

    - Guarantees a title, a cover (first) and a closing (last) slide.
    - Clamps page count to template pages_min..pages_max (truncate from the
      middle so the cover / agenda / closing survive; merge is out of scope —
      truncation reports a warning).
    - Per content-ish slide: clamps bullet count and bullet length (kills
      overflow), auto-tags number-ish bullets as ``highlight``.
    - Drops empty / malformed slides, normalizes kinds.

    Returns (outline, warnings).
    """
    warnings: List[str] = []
    if not isinstance(outline, dict):
        return {"title": "Presentation", "slides": []}, ["outline is not a dict"]
    if not isinstance(outline.get("slides"), list):
        return {"title": str(outline.get("title") or "Presentation"), "slides": []}, \
            ["outline has no 'slides' list"]

    title = str(outline.get("title") or "Presentation").strip() or "Presentation"
    raw_slides = outline["slides"]
    cons = template["constraints"]

    # 1. Normalize each slide.
    slides: List[Dict[str, Any]] = []
    for i, s in enumerate(raw_slides):
        if not isinstance(s, dict):
            continue
        kind = str(s.get("type") or "content").lower()
        if kind not in SLIDE_KINDS:
            warnings.append(f"slide {i + 1}: unknown type {kind!r} → content")
            kind = "content"
        s_title = str(s.get("title") or "").strip()
        if not s_title:
            s_title = f"Page {i + 1}"
        slide: Dict[str, Any] = {
            "type": kind,
            "title": s_title[:120],
        }
        subtitle = str(s.get("subtitle") or "").strip()
        if subtitle:
            slide["subtitle"] = subtitle[:200]
        notes = str(s.get("speaker_notes") or s.get("notes") or "").strip()
        if notes:
            slide["speaker_notes"] = notes[:600]

        if kind in {"content", "data", "timeline", "conclusion"}:
            bullets = [str(b) for b in (s.get("bullets") or []) if str(b or "").strip()]
            lo, hi = cons["bullets_min"], cons["bullets_max"]
            if len(bullets) > hi:
                warnings.append(f"slide {i + 1} ({kind}): {len(bullets)} bullets → clamped to {hi}")
                bullets = bullets[:hi]
            elif len(bullets) < lo:
                warnings.append(f"slide {i + 1} ({kind}): {len(bullets)} bullets → padded to {lo}")
                bullets = bullets + [""] * (lo - len(bullets))
            if kind == "data" and len(bullets) > cons["max_cards"]:
                warnings.append(f"data slide {i + 1}: cards clamped to {cons['max_cards']}")
                bullets = bullets[: cons["max_cards"]]
            bullets = [_clamp_bullet(b, template) for b in bullets]
            # Auto-highlight: number-ish bullets or explicit highlight list.
            highlight = set(str(h) for h in (s.get("highlight") or []))
            if cons.get("auto_highlight_numbers", True):
                for b in bullets:
                    if _is_numberish(b):
                        highlight.add(b)
            slide["bullets"] = bullets
            if highlight:
                slide["highlight"] = sorted(highlight)
        elif kind in {"title", "agenda", "section", "quote", "closing"}:
            bullets = [str(b) for b in (s.get("bullets") or []) if str(b or "").strip()]
            if bullets:
                slide["bullets"] = [_clamp_bullet(b, template) for b in bullets[: cons["max_cards"]]]
        slides.append(slide)

    # 2. Guarantee cover first / closing last.
    if not slides or slides[0].get("type") != "title":
        slides.insert(0, {"type": "title", "title": title, "subtitle": "Generated from source document"})
    if slides[-1].get("type") != "closing":
        slides.append({"type": "closing", "title": "Thank You", "subtitle": "Generated with LangConfig"})

    # 3. Clamp page count (optional — the raw gen_pptx path skips this).
    if clamp_pages and len(slides) > cons["pages_max"]:
        excess = len(slides) - cons["pages_max"]
        warnings.append(f"deck has {len(slides)} slides → truncated to {cons['pages_max']}")
        # Drop from the middle (after cover+agenda, before closing).
        head = slides[:2]
        tail = slides[-1:]
        middle = slides[2:-1]
        middle = middle[: max(0, cons["pages_max"] - len(head) - len(tail))]
        slides = head + middle + tail
    elif clamp_pages and len(slides) < cons["pages_min"]:
        warnings.append(
            f"deck has {len(slides)} slides (< {cons['pages_min']}); "
            "consider a longer source or more granular outline"
        )

    return {"title": title, "slides": slides}, warnings
