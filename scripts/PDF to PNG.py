#!/usr/bin/env python3
"""
PDF to PNG.py — render PDF page(s) to PNG image(s).

Handles three input shapes:
  1. A single-page PDF          -> one X.png
  2. A multi-page PDF           -> one X-<page>.png per page (matching the
                                    "-N" suffix convention used for the scan
                                    files), zero-padded so filenames sort in
                                    page order (e.g. X-01.png, X-02.png, ...)
  3. A folder of PDFs           -> every *.pdf in the folder is converted per
                                    the two rules above (mixed single/multi
                                    page files are fine).

Resolution is controlled by --dpi (default 480).

Dependency (not in the standard library):
    pip install pymupdf

Usage:
    python3 "PDF to PNG.py" scan.pdf
    python3 "PDF to PNG.py" scan.pdf --dpi 600
    python3 "PDF to PNG.py" path/to/folder --outdir png/
"""

from __future__ import annotations

import argparse
from pathlib import Path

import fitz  # PyMuPDF


def pdf_to_png(pdf_path: Path, outdir: Path | None = None, dpi: int = 480) -> list[str]:
    """Render one PDF to PNG(s). Single page -> <stem>.png; multi-page ->
    <stem>-<NN>.png per page, zero-padded to preserve page order."""
    pdf_path = Path(pdf_path)
    outdir = Path(outdir) if outdir else pdf_path.parent
    outdir.mkdir(parents=True, exist_ok=True)

    zoom = dpi / 72  # PDF points are 1/72 inch; fitz's default is 72 dpi.
    matrix = fitz.Matrix(zoom, zoom)
    stem = pdf_path.stem
    written = []

    with fitz.open(pdf_path) as doc:
        n_pages = doc.page_count
        pad = len(str(n_pages))
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=matrix)
            if n_pages == 1:
                out_path = outdir / f"{stem}.png"
            else:
                out_path = outdir / f"{stem}-{i:0{pad}d}.png"
            pix.save(str(out_path))
            written.append(str(out_path))

    return written


def process_path(in_path: Path, outdir: Path | None = None, dpi: int = 480) -> dict:
    """Convert a single PDF, or every PDF in a folder, to PNG(s)."""
    in_path = Path(in_path)
    results = {}

    if in_path.is_dir():
        pdf_files = sorted(in_path.glob("*.pdf"))
        for pdf_file in pdf_files:
            results[str(pdf_file)] = pdf_to_png(pdf_file, outdir=outdir, dpi=dpi)
    else:
        results[str(in_path)] = pdf_to_png(in_path, outdir=outdir, dpi=dpi)

    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Render a PDF (or every PDF in a folder) to PNG image(s).")
    ap.add_argument("inputs", nargs="+", type=Path,
                     help="PDF file(s) and/or folder(s) of PDFs to convert")
    ap.add_argument("--outdir", type=Path, default=None,
                     help="output directory (default: alongside each input PDF)")
    ap.add_argument("--dpi", type=int, default=480,
                     help="rendering resolution in dots per inch (default: 480)")
    args = ap.parse_args(argv)

    for path in args.inputs:
        results = process_path(path, outdir=args.outdir, dpi=args.dpi)
        for source, outputs in results.items():
            print(f"{source}: wrote {', '.join(Path(o).name for o in outputs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
