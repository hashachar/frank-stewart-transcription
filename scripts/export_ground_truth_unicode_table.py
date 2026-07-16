#!/usr/bin/env python3
"""
export_ground_truth_unicode_table.py — .txt and PDF versions of the
ground-truth sign inventory (companion to audit_ground_truth_unicode.py).

Produces a clean one-table report: Sign | Unicode | Character Name | Count,
for every combining mark, diacritic-bearing letter, modifier letter
(ʿayn/hamza), and quotation/apostrophe-family character found inside
{curly-brace} spans in ground-truth/*.docx. Plain ASCII punctuation is
excluded (see audit_ground_truth_unicode.classify). Both output formats
carry the same short explanation of precomposed vs. decomposed diacritics
(see EXPLANATION_NOTE below) so the table is self-contained without needing
to re-derive why, e.g., 't with dot below' and 'b with dot below' don't share
a code point even though both use the same dot-below mark.

Rendering notes (PDF):
  - A bare combining mark (e.g. COMBINING DOT BELOW) is prefixed with a
    dotted circle (U+25CC) so it displays attached to something, per the
    usual Unicode-chart convention for isolated combining marks.
  - Uses Times New Roman with Arial Unicode MS as fallback — both were
    checked (via fontTools cmap inspection) to cover every sign in this
    corpus, including Latin Extended Additional dot-below/line-below
    letters and IPA modifier letters.
  - Table rows have `break-inside: avoid` so a row's sign and its
    Unicode/name/count cells can never be split across a page boundary
    (WeasyPrint will otherwise happily orphan a tall combining-mark glyph
    onto the next page while leaving the rest of the row behind).

Dependency (not in the standard library):
    pip install weasyprint

Usage:
    python3 export_ground_truth_unicode_table.py              # writes both .txt and .pdf
    python3 export_ground_truth_unicode_table.py --txt        # .txt only
    python3 export_ground_truth_unicode_table.py --pdf        # .pdf only
    python3 export_ground_truth_unicode_table.py --out reports/table   # custom stem (no extension)
"""

from __future__ import annotations

import argparse
import sys
import textwrap
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_ground_truth_unicode import extract_spans, classify  # noqa: E402

KEEP_CLASSES = {"combining_mark", "precomposed_diacritic_letter", "modifier_letter", "quote_or_apostrophe"}

EXPLANATION_NOTE = (
    "Unicode offers two ways to write an accented "
    "letter. PRECOMPOSED gives one dedicated code point to a specific letter+diacritic pair "
    "(e.g. U+1E6D for ‘t with dot below’). DECOMPOSED instead writes the plain base "
    "letter followed by a separate combining mark (e.g. ‘t’ + U+0323 COMBINING DOT "
    "BELOW), which the font stacks onto whatever precedes it. Both render identically in a "
    "well-built font. Precomposed code points exist only for combinations common enough to "
    "have been given their own Unicode slot — which is why ‘t with dot below’ "
    "and ‘b with dot below’ have unrelated-looking numbers even though both are built "
    "from the same dot-below mark. Rarer combinations (e.g. ‘d with line below’ plus "
    "an extra dot below) have no dedicated slot and must fall back to the combining-mark route. "
    "A Character Name starting with ‘Combining’ below is one of these bare marks, not "
    "a full letter on its own."
)

PAGE_CSS = """
@page {
    size: Letter;
    margin: 0.85in 0.9in;
    @bottom-center {
        content: "Page " counter(page) " of " counter(pages);
        font-family: "Times New Roman", "Arial Unicode MS", sans-serif;
        font-size: 9pt;
        color: #888;
    }
}
* { box-sizing: border-box; }
body {
    font-family: "Times New Roman", "Arial Unicode MS", sans-serif;
    color: #1a1a1a;
    margin: 0;
}
h1 {
    font-size: 19pt;
    font-weight: bold;
    margin: 0 0 2pt 0;
    letter-spacing: 0.2pt;
}
.subtitle {
    font-size: 10pt;
    color: #555;
    margin: 0 0 18pt 0;
}
.note {
    font-size: 9pt;
    line-height: 1.45;
    color: #444;
    background: #f7f5ee;
    border-left: 3pt solid #b8ab7a;
    padding: 9pt 12pt;
    margin: 0 0 16pt 0;
}
.note b { color: #1a1a1a; }
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 11pt;
}
thead {
    display: table-header-group;
}
thead th {
    text-align: left;
    font-size: 9.5pt;
    letter-spacing: 0.5pt;
    text-transform: uppercase;
    color: #ffffff;
    background: #2b2b2b;
    padding: 7pt 10pt;
    border: none;
}
thead th.count-h { text-align: right; }
thead th.sign-h { text-align: center; }
tbody tr {
    break-inside: avoid;
    page-break-inside: avoid;
}
tbody tr:nth-child(even) {
    background: #f4f4f4;
}
tbody td {
    padding: 5pt 10pt;
    border-bottom: 0.5pt solid #ddd;
    vertical-align: middle;
}
td.sign {
    font-size: 17pt;
    text-align: center;
    width: 14%;
}
td.cp {
    font-family: "Courier New", monospace;
    font-size: 10pt;
    color: #444;
    width: 16%;
}
td.name { width: 52%; }
td.count {
    text-align: right;
    width: 18%;
    font-variant-numeric: tabular-nums;
    color: #333;
}
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Ground-Truth Diacritic &amp; Punctuation Sign Inventory</title>
<style>{css}</style>
</head>
<body>
<h1>Ground-Truth Diacritic &amp; Punctuation Sign Inventory</h1>
<div class="subtitle">
Every combining mark, diacritic-bearing letter, modifier letter, and quotation/apostrophe-family
character found inside {{curly-brace}} editorial annotations across {source_list} &middot; generated {today}
</div>
<div class="note"><b>Precomposed vs. decomposed:</b> {note}</div>
<table>
<thead>
<tr>
<th class="sign-h">Sign</th>
<th>Unicode</th>
<th>Character Name</th>
<th class="count-h">Count</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
</body>
</html>
"""


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _display_sign(ch: str) -> str:
    if unicodedata.category(ch) in ("Mn", "Mc", "Me"):
        return "◌" + ch  # dotted circle so a bare combining mark renders visibly
    return ch


def build_char_counts(docx_files: list[Path]) -> Counter:
    char_count: Counter = Counter()
    for f in docx_files:
        spans, _ = extract_spans(f)
        for _, s in spans:
            for ch in s:
                char_count[ch] += 1
    return char_count


def build_rows(char_count: Counter) -> list[tuple[str, int]]:
    rows = [(ch, cnt) for ch, cnt in char_count.items() if classify(ch) in KEEP_CLASSES]
    rows.sort(key=lambda r: -r[1])
    return rows


def build_html(rows: list[tuple[str, int]], source_list: str) -> str:
    row_html = []
    for ch, cnt in rows:
        sign = _esc(_display_sign(ch))
        cp = f"U+{ord(ch):04X}"
        name = unicodedata.name(ch, "<no name>").title()
        row_html.append(
            f"<tr><td class='sign'>{sign}</td><td class='cp'>{cp}</td>"
            f"<td class='name'>{_esc(name)}</td><td class='count'>{cnt}</td></tr>"
        )

    return HTML_TEMPLATE.format(
        css=PAGE_CSS,
        source_list=source_list,
        today=date.today().isoformat(),
        note=_esc(EXPLANATION_NOTE),
        rows="".join(row_html),
    )


def render_txt(rows: list[tuple[str, int]], source_list: str) -> str:
    lines = []
    lines.append("Ground-Truth Diacritic & Punctuation Sign Inventory")
    lines.append(
        f"Every combining mark, diacritic-bearing letter, modifier letter, and "
        f"quotation/apostrophe-family character found inside {{curly-brace}} editorial "
        f"annotations across {source_list} - generated {date.today().isoformat()}"
    )
    lines.append("")
    lines.append("Precomposed vs. decomposed:")
    lines.extend(textwrap.wrap(EXPLANATION_NOTE, width=78))
    lines.append("")
    lines.append(f'{"Sign":<6}{"Unicode":<10}{"Name":<45}{"Count"}')
    lines.append("-" * 75)
    for ch, cnt in rows:
        sign = _display_sign(ch)
        cp = f"U+{ord(ch):04X}"
        name = unicodedata.name(ch, "<no name>").title()
        lines.append(f"{sign:<6}{cp:<10}{name:<45}{cnt}")
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    BASE = Path(__file__).resolve().parent.parent

    ap = argparse.ArgumentParser(
        description="Export the ground-truth diacritic/quotation sign inventory as .txt and/or PDF.")
    ap.add_argument("inputs", nargs="*", type=Path,
                     help=".docx files to scan (default: all of ground-truth/*.docx)")
    ap.add_argument("--out", type=Path, default=None,
                     help="output path stem, no extension "
                          "(default: reports/ground_truth_unicode_table)")
    ap.add_argument("--txt", action="store_true", help="write only the .txt table")
    ap.add_argument("--pdf", action="store_true", help="write only the PDF table")
    args = ap.parse_args(argv)

    docx_files = args.inputs if args.inputs else sorted((BASE / "ground-truth").glob("*.docx"))
    if not docx_files:
        print("No .docx files found.", file=sys.stderr)
        return 1

    formats = []
    if args.txt:
        formats.append("txt")
    if args.pdf:
        formats.append("pdf")
    if not formats:
        formats = ["txt", "pdf"]

    out_stem = args.out or (BASE / "reports" / "ground_truth_unicode_table")
    out_stem.parent.mkdir(parents=True, exist_ok=True)

    char_count = build_char_counts(docx_files)
    rows = build_rows(char_count)
    source_list = ", ".join(f.name for f in docx_files)

    if "txt" in formats:
        txt_path = out_stem.with_suffix(".txt")
        txt_path.write_text(render_txt(rows, source_list), encoding="utf-8")
        print(f"wrote {txt_path}")

    if "pdf" in formats:
        pdf_path = out_stem.with_suffix(".pdf")
        html = build_html(rows, source_list)
        from weasyprint import HTML
        HTML(string=html).write_pdf(str(pdf_path))
        print(f"wrote {pdf_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
