#!/usr/bin/env python3
"""
count_diacritics.py — Diacritical mark detection counter for transcription QA.

RATIONALE
---------
The Step 1 transcription script (transcribe.py) encodes every diacritical mark
and special character as an interim notation token of the form {token-name},
e.g. a{macron}, t{dotbelow}, {apostrophe-ayn}, {theta-symbol}.

Before running the Step 2 normalization script, or before committing to a model
configuration for a large batch, it is useful to count how many of these tokens
appear in each output file. This count serves as a proxy for transcription
thoroughness on diacritical marks — the hardest part of the task.

PURPOSE
-------
Compare multiple transcription output files (e.g. from different model configs)
to answer:

  - How many diacritical marks did each configuration detect on the same page?
  - Which specific mark types differ between configurations?
  - Is a cheaper/faster config missing marks, or are the counts comparable?

A configuration that detects significantly FEWER marks is likely missing some.
One that detects significantly MORE may be over-detecting (false positives).
Neither count alone is the ground truth — human review of divergent tokens
remains necessary — but the count quickly flags which configs warrant scrutiny.

STRUCTURAL TOKENS (excluded from count)
----------------------------------------
The following tokens are scaffolding, not diacritics, and are always excluded:
  {LB}           line break
  {HEADING}      heading open marker
  {/HEADING}     heading close marker
  {INDENT}       indentation marker

Everything else inside curly braces is counted as a diacritical/special token.

USAGE
-----
  # Compare all .txt files in a folder (non-recursive)
  python3 count_diacritics.py outputs/gpt-5.5_effort-high_CI-on/

  # Compare specific files
  python3 count_diacritics.py file1.txt file2.txt file3.txt

  # Compare all configs under outputs/ automatically
  python3 count_diacritics.py --all-configs

  # Save report to file
  python3 count_diacritics.py --all-configs --out report.txt

Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

# Structural tokens to exclude from diacritic counts
STRUCTURAL = {"LB", "HEADING", "/HEADING", "INDENT"}

# Known diacritic token names for grouping in the summary
KNOWN_TOKENS = {
    "macron", "dotbelow", "dotabove", "acute",
    "theta-symbol", "apostrophe-ayn", "apostrophe-hamza",
}

_TOKEN_RE = re.compile(r"\{([^{}]+)\}")


def count_file(path: Path) -> tuple[Counter, int, int]:
    """
    Parse one interim-notation .txt file.

    Returns:
        counts   Counter of token-name -> occurrence count (structural excluded)
        total    total diacritic tokens found
        structural_count  number of structural tokens found (for sanity check)
    """
    text = path.read_text(encoding="utf-8")
    counts: Counter = Counter()
    structural_count = 0

    for m in _TOKEN_RE.finditer(text):
        token = m.group(1).strip()
        if token in STRUCTURAL:
            structural_count += 1
        else:
            counts[token] += 1

    return counts, sum(counts.values()), structural_count


def find_txt_files(paths: list[Path]) -> list[Path]:
    """
    Expand a mixed list of files and directories into .txt file paths.
    Directories are searched non-recursively; only files ending in .txt
    that do NOT already have .literal or .normalized in their name are included
    (those are Step 2 outputs and should not be re-counted).
    """
    result = []
    for p in paths:
        if p.is_dir():
            for f in sorted(p.glob("*.txt")):
                if ".literal." not in f.name and ".normalized." not in f.name:
                    result.append(f)
        elif p.is_file() and p.suffix == ".txt":
            result.append(p)
        else:
            print(f"Warning: skipping {p} (not a .txt file or directory)", file=sys.stderr)
    return result


def find_all_configs(base: Path) -> list[Path]:
    """
    Auto-discover one representative .txt file per config subfolder under
    outputs/. Returns the first qualifying .txt in each subfolder.
    """
    outputs_dir = base / "outputs"
    result = []
    for subfolder in sorted(outputs_dir.iterdir()):
        if not subfolder.is_dir():
            continue
        txts = [f for f in sorted(subfolder.glob("*.txt"))
                if ".literal." not in f.name and ".normalized." not in f.name]
        if txts:
            result.append(txts[0])
    return result


def format_report(file_counts: list[tuple[Path, Counter, int, int]]) -> str:
    """Render the comparison report as plain text."""
    lines = []
    lines.append("=" * 72)
    lines.append("DIACRITICAL MARK DETECTION COMPARISON")
    lines.append("=" * 72)

    # Collect all token names seen across all files
    all_tokens = sorted(
        set(t for _, counts, _, _ in file_counts for t in counts),
        key=lambda t: (t not in KNOWN_TOKENS, t)
    )

    # Per-file summary
    for path, counts, total, struct in file_counts:
        label = path.parent.name if path.parent.name != "outputs" else path.name
        lines.append(f"\n[{label}]")
        lines.append(f"  File              : {path.name}")
        lines.append(f"  Total diacritics  : {total}")
        lines.append(f"  Structural tokens : {struct}  (excluded)")
        lines.append(f"  By type:")
        for token in all_tokens:
            n = counts.get(token, 0)
            bar = "█" * min(n, 40)
            lines.append(f"    {{{'%s'%token:<22}}}  {n:>4}  {bar}")

    # Side-by-side comparison table
    lines.append("\n" + "=" * 72)
    lines.append("COMPARISON TABLE")
    lines.append("=" * 72)

    col_w = 14
    labels = [p.parent.name[:col_w] for p, *_ in file_counts]
    header = f"{'Token':<26}" + "".join(f"{l:>{col_w}}" for l in labels)
    lines.append(header)
    lines.append("-" * len(header))

    for token in all_tokens:
        row_vals = [counts.get(token, 0) for _, counts, _, _ in file_counts]
        differs = len(set(row_vals)) > 1
        marker = "  ◄ differs" if differs else ""
        row = f"  {{{'%s'%token:<24}}}" + "".join(f"{v:>{col_w}}" for v in row_vals) + marker
        lines.append(row)

    # Totals row
    totals = [total for _, _, total, _ in file_counts]
    lines.append("-" * len(header))
    totals_row = f"  {'TOTAL':<24}" + "".join(f"{t:>{col_w}}" for t in totals)
    lines.append(totals_row)

    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    BASE = Path(__file__).resolve().parent.parent

    ap = argparse.ArgumentParser(
        description="Count diacritical mark tokens in interim-notation transcription files.")
    ap.add_argument("inputs", nargs="*", type=Path,
                    help=".txt files or directories to analyse")
    ap.add_argument("--all-configs", action="store_true",
                    help="Auto-discover all config subfolders under outputs/")
    ap.add_argument("--out", type=Path, default=None,
                    help="Save report to this file in addition to printing")
    args = ap.parse_args(argv)

    if args.all_configs:
        txt_files = find_all_configs(BASE)
    elif args.inputs:
        txt_files = find_txt_files(args.inputs)
    else:
        ap.print_help()
        return 1

    if not txt_files:
        print("No .txt files found.", file=sys.stderr)
        return 1

    file_counts = []
    for f in txt_files:
        counts, total, struct = count_file(f)
        file_counts.append((f, counts, total, struct))

    report = format_report(file_counts)
    print(report)

    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"Report saved → {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
