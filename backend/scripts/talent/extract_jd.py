#!/usr/bin/env python3
"""Read the job-description folder into `requirements.json` — role, floor, years, skills.

The client sent ten 职务说明书 in three formats (.doc x6, .docx, .xlsx x2). Each conversion is done by
whatever the host actually has, in this order, and the choice is printed so a reader can tell which
path produced a field:

    .doc   antiword → catdoc → textutil (macOS) → LibreOffice
    .docx  python-docx
    .xlsx  openpyxl (every sheet, every non-empty row)

Nothing is inferred beyond what the text says: a JD that states no education line yields
`education_floor: null` and reports `missing: ["education_floor"]`. `check_abox`'s A5 coverage and the
role definitions are then written against what the client actually stated — a role with an unknown
floor simply cannot be claimed to match on education.

Exit: 0 wrote requirements, 1 folder empty, 2 a hard failure (no converter, unreadable file).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from scripts.talent.jd_parse import as_ttl_comment, requirements_from_text, role_from_filename  # noqa: E402

DOC_CONVERTERS = ("antiword", "catdoc", "textutil")


def _doc_text(path: pathlib.Path) -> tuple[str, str]:
    if shutil.which("antiword"):
        run = subprocess.run(["antiword", str(path)], capture_output=True, text=True, timeout=120)
        if run.returncode == 0 and run.stdout.strip():
            return run.stdout, "antiword"
    if shutil.which("catdoc"):
        run = subprocess.run(["catdoc", str(path)], capture_output=True, text=True, timeout=120)
        if run.returncode == 0 and run.stdout.strip():
            return run.stdout, "catdoc"
    if shutil.which("textutil"):
        run = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(path)],
                             capture_output=True, text=True, timeout=120)
        if run.returncode == 0 and run.stdout.strip():
            return run.stdout, "textutil"
    for exe in ("libreoffice", "soffice"):
        if shutil.which(exe):
            outdir = pathlib.Path(str(path) + ".conv")
            outdir.mkdir(exist_ok=True)
            subprocess.run([exe, "--headless", "--convert-to", "txt:Text", "--outdir", str(outdir),
                            str(path)], capture_output=True, timeout=300)
            produced = list(outdir.glob("*.txt"))
            if produced:
                return produced[0].read_text(encoding="utf-8", errors="replace"), exe
    return "", "none"


def _docx_text(path: pathlib.Path) -> tuple[str, str]:
    from docx import Document
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append("\t".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts), "python-docx"


def _xlsx_text(path: pathlib.Path) -> tuple[str, str]:
    from openpyxl import load_workbook
    wb = load_workbook(str(path), data_only=True)
    out: list[str] = []
    for sheet in wb.worksheets:
        out.append(f"## sheet {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c not in (None, "")]
            if cells:
                out.append("\t".join(cells))
    return "\n".join(out), "openpyxl"


def text_of(path: pathlib.Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix == ".doc":
        return _doc_text(path)
    if suffix == ".docx":
        return _docx_text(path)
    if suffix in (".xlsx", ".xlsm"):
        return _xlsx_text(path)
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace"), "text"
    return "", "unsupported"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="folder of job descriptions")
    ap.add_argument("--out", required=True, help="requirements.json to write")
    ap.add_argument("--texts", default="", help="also dump each JD as .txt here (for review)")
    args = ap.parse_args()

    src = pathlib.Path(args.input).expanduser().resolve()
    if not src.is_dir():
        print(f"nothing to do: no such folder {src}")
        return 1
    docs = sorted(p for p in src.iterdir()
                  if p.is_file() and p.suffix.lower() in (".doc", ".docx", ".xlsx", ".xlsm", ".txt")
                  and not p.name.startswith("._"))
    if not docs:
        print(f"nothing to do: no job descriptions under {src}")
        return 1

    texts_dir = pathlib.Path(args.texts).expanduser().resolve() if args.texts else None
    if texts_dir:
        texts_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for path in docs:
        try:
            text, how = text_of(path)
        except Exception as exc:
            print(f"  ! {path.name}: {type(exc).__name__}: {exc}")
            continue
        role = role_from_filename(path.stem)
        req = requirements_from_text(role, text)
        req["source_file"] = path.name
        req["converted_by"] = how
        rows.append(req)
        if texts_dir:
            (texts_dir / f"{path.stem}.txt").write_text(text, encoding="utf-8")
        print(f"  {role:10s} [{how:12s}] {as_ttl_comment(req)}")

    out = pathlib.Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    complete = [r for r in rows if not r["missing"]]
    print(f"\nwrote {len(rows)} requirement record(s) to {out}")
    print(f"  fully stated   : {len(complete)}/{len(rows)}")
    print(f"  roles          : {', '.join(r['role'] for r in rows)}")
    missing = sorted({m for r in rows for m in r["missing"]})
    if missing:
        print(f"  NOT stated by some JDs: {missing} — the ontology must not invent them")
    converters = sorted({r["converted_by"] for r in rows})
    print(f"  converters     : {converters}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
