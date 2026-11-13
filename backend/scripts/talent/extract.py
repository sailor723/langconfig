#!/usr/bin/env python3
"""Turn the client's CV dossier into candidate records — OCR once, cached, reproducible.

The 277 CVs are scans (measured: 0 extractable characters, one /Image per page, no /Font), so every
byte of text comes from OCR and every OCR run is worth caching: a second pass over the dossier must
cost nothing and must produce the SAME text, or the ontology's ABox would drift between builds for a
reason nobody can see. The cache key is the file's sha256 plus the dpi and language, so changing
either of those deliberately invalidates it.

    backend/.venv/bin/python backend/scripts/talent/extract.py \\
        --input "client/team-4/unzipped/简历307份" --out /tmp/team4/candidates.jsonl

What it refuses to do: invent. A résumé that OCR cannot read yields `ocr_chars: 0` and warnings
("no OCR text — the record rests on path and filename only"), not a candidate with no skills and no
experience. The ABox builder turns those into `:Unknown` individuals; a zero would be a lie about a
person.

Exit: 0 wrote records, 1 nothing to do, 2 a hard failure (missing input, missing OCR binary).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # backend/ on sys.path, for `scripts.talent.parse`

from scripts.talent.parse import build_record  # noqa: E402


def _sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()



def _rasterise(pdf: pathlib.Path, workdir: pathlib.Path, dpi: int) -> tuple[list[pathlib.Path], str]:
    """(page PNGs, which renderer) — pdftoppm if present (poppler), else PyMuPDF.

    Measured 2026-11-14: the dev box has tesseract but NOT poppler, and the first OCR run reported
    "missing pdftoppm" for all 277 files while looking like an OCR-quality problem. A second renderer
    keeps the pipeline honest on both machines: the deployment has poppler, this box does not.
    """
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm:
        base = workdir / "page"
        subprocess.run([pdftoppm, "-r", str(dpi), "-png", str(pdf), str(base)],
                       capture_output=True, text=True, timeout=600)
        pages = sorted(workdir.glob("page*.png"))
        if pages:
            return pages, "pdftoppm"
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(pdf))
        scale = dpi / 72.0
        out: list[pathlib.Path] = []
        for index, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            target = workdir / f"page-{index + 1}.png"
            pix.save(str(target))
            out.append(target)
        doc.close()
        return out, "pymupdf"
    except Exception as exc:
        return [], f"no renderer: {type(exc).__name__}: {exc}"


def ocr_pdf(pdf: pathlib.Path, cache: pathlib.Path, dpi: int, lang: str) -> tuple[str, str]:
    """(text, how) — `how` is `cache` on a hit, `ocr` after a run, `error: …` when it failed."""
    key = f"{_sha(pdf)[:32]}-{dpi}-{lang.replace('+', '_')}"
    cached = cache / f"{key}.txt"
    if cached.is_file():
        return cached.read_text(encoding="utf-8", errors="replace"), "cache"

    tesseract = shutil.which("tesseract")
    if not tesseract:
        return "", "error: missing tesseract on PATH (apt-get install tesseract-ocr tesseract-ocr-chi-sim)"

    with tempfile.TemporaryDirectory() as td:
        pages, how = _rasterise(pdf, pathlib.Path(td), dpi)
        if not pages:
            return "", f"error: no page rendered ({how})"
        texts: list[str] = []
        for page in pages:
            run = subprocess.run([tesseract, str(page), "stdout", "-l", lang],
                                 capture_output=True, text=True, timeout=300)
            texts.append(run.stdout or "")
        text = "\n".join(texts)

    cache.mkdir(parents=True, exist_ok=True)
    cached.write_text(text, encoding="utf-8")
    return text, "ocr"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="a CV PDF, or a directory tree of them")
    ap.add_argument("--out", required=True, help="JSONL of candidate records")
    ap.add_argument("--cache", default="", help="OCR text cache (default: <out dir>/ocr-cache)")
    ap.add_argument("--root", default="", help="relative paths are computed from here (default: --input)")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--lang", default="chi_sim+eng")
    ap.add_argument("--limit", type=int, default=0, help="stop after N files (a spike, not a build)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-ocr", action="store_true",
                    help="path/filename only — the deterministic half, useful for a fast census")
    args = ap.parse_args()

    src = pathlib.Path(args.input).expanduser().resolve()
    if not src.exists():
        print(f"nothing to do: no such input {src}")
        return 2
    root = pathlib.Path(args.root).expanduser().resolve() if args.root else (src if src.is_dir() else src.parent)
    out = pathlib.Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cache = pathlib.Path(args.cache).expanduser().resolve() if args.cache else out.parent / "ocr-cache"

    # macOS leaves AppleDouble sidecars next to every file: `._【业务跟单…】.pdf`. They end in `.pdf`,
    # so `rglob("*.pdf")` doubles the dossier (measured on the deployment: 554 "PDFs" for 277 real
    # ones) and OCR them into garbage that looks like an unreadable CV. Skip them by name.
    def _is_real(pdf: pathlib.Path) -> bool:
        return not pdf.name.startswith("._") and pdf.name != ".DS_Store"

    pdfs = sorted([p for p in ([src] if src.is_file() else src.rglob("*.pdf")) if _is_real(p)])
    if args.limit:
        pdfs = pdfs[: args.limit]
    if not pdfs:
        print(f"nothing to do: no PDFs under {src}")
        return 1

    print(f"input:  {src}")
    print(f"pdfs:   {len(pdfs)}")
    print(f"out:    {out}")
    print(f"cache:  {cache}{'  (disabled)' if args.no_ocr else ''}")

    def one(pdf: pathlib.Path) -> dict:
        rel = str(pdf.relative_to(root)) if pdf.is_relative_to(root) else str(pdf)
        if args.no_ocr:
            text, how = "", "skipped"
        else:
            text, how = ocr_pdf(pdf, cache, args.dpi, args.lang)
        rec = build_record(rel, pdf.stem, text)
        row = rec.to_dict()
        row["_text_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""
        row["ocr_how"] = how
        if how.startswith("error"):
            row["warnings"].append(how)
        return row

    rows: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for row in pool.map(one, pdfs):
            rows.append(row)

    # The dossier contains the same person twice under different names (`黄__ 6年.pdf` and
    # `黄__ 6年 (1).pdf`, byte-identical OCR). Counting them as two candidates would inflate every
    # per-role match count, so the duplicate is MARKED rather than dropped: the ABox can then say
    # ":sameAs" or refuse, and a human can see the file it came from.
    seen: dict[str, str] = {}
    for row in rows:
        digest = row.pop("_text_hash", "")
        if not digest:
            continue
        if digest in seen:
            row.setdefault("warnings", []).append(
                f"same scanned content as {seen[digest]} — likely the same person twice")
            row["duplicate_of"] = seen[digest]
        else:
            seen[digest] = row["source_file"]

    with out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    total = len(rows)
    with_text = sum(1 for r in rows if r["ocr_chars"] > 0)
    with_years = sum(1 for r in rows if r["years_experience"]["value"] is not None)
    with_skills = sum(1 for r in rows if r["skills"])
    with_role = sum(1 for r in rows if r["applied_role"]["value"])
    with_edu = sum(1 for r in rows if r["education"]["value"])
    errors = [r for r in rows if r["ocr_how"].startswith("error")]

    print(f"\nwrote {total} record(s) to {out}")
    print(f"  OCR text present : {with_text}/{total}")
    print(f"  applied role     : {with_role}/{total}  (filename)")
    print(f"  years experience : {with_years}/{total}  (unknown stays unknown)")
    print(f"  education        : {with_edu}/{total}  (OCR)")
    print(f"  any skill        : {with_skills}/{total}  (tolerant OCR patterns)")
    if errors:
        print(f"  OCR failures     : {len(errors)}  e.g. {errors[0]['source_file']} — {errors[0]['warnings'][-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
