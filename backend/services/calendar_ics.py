# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Read `.ics` files into calendar events (read-only view).

Two deliberate choices:

1. **Hand-rolled instead of ``icalendar``.** The platform does not ship that
   dependency, and nothing here needs RRULE/attendee semantics — we need
   "when and what", per VEVENT.
2. **Tolerant instead of strict.** The files are written by an LLM, so a
   malformed file must not raise: whatever cannot be read comes back to the
   caller as a skipped file, and whatever can be read is reported as-is —
   *including* the fact that a floating time has no timezone, so the UI shows
   the literal clock time instead of inventing a local one.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

# 20261103T140000 / 20261103T140000Z
_DATETIME_BASIC = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z)?$")
# 20261103 (all-day)
_DATE_BASIC = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
# PT1H / PT90M / P1D / P1DT2H30M
_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$", re.IGNORECASE)

# Escaped text per RFC 5545 §3.3.11.
_UNESCAPE = (("\\N", "\n"), ("\\n", "\n"), ("\\,", ","), ("\\;", ";"), ("\\\\", "\\"))


def unfold(raw: str) -> List[str]:
    """Split into logical lines, joining RFC 5545 folded continuations.

    A folded line continues on the next physical line, which starts with a
    single space or tab; the whitespace itself is not part of the value.
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines: List[str] = []
    for line in text.split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return [ln for ln in lines if ln.strip()]


def _unescape(value: str) -> str:
    for escaped, plain in _UNESCAPE:
        value = value.replace(escaped, plain)
    return value.strip()


def _split_property(line: str):
    """``DTSTART;TZID=Asia/Shanghai:20261103T140000`` → (name, params, value)."""
    if ":" not in line:
        return None, {}, ""
    head, value = line.split(":", 1)
    parts = head.split(";")
    name = parts[0].strip().upper()
    params: Dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, val = part.split("=", 1)
            params[key.strip().upper()] = val.strip()
    return name, params, value.strip()


def _parse_when(value: str, params: Dict[str, str]):
    """Parse one date/date-time property into (iso, timezone, all_day)."""
    raw = value.strip()
    tzid = params.get("TZID") or None
    if params.get("VALUE", "").upper() == "DATE" or _DATE_BASIC.match(raw):
        m = _DATE_BASIC.match(raw)
        if not m:
            return None, None, False
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d.isoformat(), tzid, True
    m = _DATETIME_BASIC.match(raw)
    if not m:
        return None, None, False
    dt = datetime(
        int(m.group(1)), int(m.group(2)), int(m.group(3)),
        int(m.group(4)), int(m.group(5)), int(m.group(6)),
    )
    if m.group(7):  # trailing Z → UTC
        tzid = "UTC"
    return dt.isoformat(), tzid, False


def _add_duration(start_iso: str, all_day: bool, value: str) -> Optional[str]:
    m = _DURATION.match(value.strip())
    if not m:
        return None
    days, hours, minutes = (int(g) if g else 0 for g in m.groups())
    try:
        start = datetime.fromisoformat(start_iso)
    except ValueError:
        return None
    return (start + timedelta(days=days, hours=hours, minutes=minutes)).isoformat()


def _default_end(start_iso: str, all_day: bool) -> str:
    """No DTEND/DURATION: all-day lasts a day, a timed event an hour."""
    if all_day:
        try:
            return (date.fromisoformat(start_iso) + timedelta(days=1)).isoformat()
        except ValueError:
            return start_iso
    try:
        start = datetime.fromisoformat(start_iso)
    except ValueError:
        return start_iso
    return (start + timedelta(hours=1)).isoformat()


def parse_ics(raw: str, fallback_title: str = "") -> List[Dict[str, Any]]:
    """Return one dict per VEVENT that carries a usable start time.

    Keys: ``title``, ``start``, ``end`` (ISO 8601, naive when the file is
    floating), ``all_day``, ``timezone`` (TZID / ``"UTC"`` / None),
    ``location``, ``description``.
    """
    events: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for line in unfold(raw):
        name, params, value = _split_property(line)
        if name is None:
            continue
        if name == "BEGIN" and value.upper() == "VEVENT":
            current = {}
            continue
        if name == "END" and value.upper() == "VEVENT":
            if current and current.get("start"):
                start_iso = current["start"]
                all_day = bool(current.get("all_day"))
                end_iso = current.get("end") or _default_end(start_iso, all_day)
                events.append({
                    "title": current.get("title") or fallback_title or "(未命名日程)",
                    "start": start_iso,
                    "end": end_iso,
                    "all_day": all_day,
                    "timezone": current.get("timezone"),
                    "location": current.get("location", ""),
                    "description": current.get("description", ""),
                })
            current = None
            continue
        if current is None:
            continue
        if name == "DTSTART":
            start_iso, tzid, all_day = _parse_when(value, params)
            if start_iso:
                current["start"] = start_iso
                current["all_day"] = all_day
                if tzid:
                    current["timezone"] = tzid
        elif name == "DTEND":
            end_iso, tzid, _ = _parse_when(value, params)
            if end_iso:
                current["end"] = end_iso
                if tzid and not current.get("timezone"):
                    current["timezone"] = tzid
        elif name == "DURATION":
            if current.get("start") and not current.get("end"):
                computed = _add_duration(
                    current["start"], bool(current.get("all_day")), value
                )
                if computed:
                    current["end"] = computed
        elif name == "SUMMARY":
            current["title"] = _unescape(value)
        elif name == "LOCATION":
            current["location"] = _unescape(value)
        elif name == "DESCRIPTION":
            current["description"] = _unescape(value)

    return events
