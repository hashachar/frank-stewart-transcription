#!/usr/bin/env python3
"""
audit_ground_truth_unicode.py — Unicode consistency audit for ground-truth .docx files.

RATIONALE
---------
The human-transcribed ground-truth documents (ground-truth/*.docx) contain
editorial annotations in {curly braces}: queries, glosses, corrections, and
transliterated Bedouin Arabic words carrying diacritics (macron, dot below,
caron, etc.) and Arabic-specific signs (ʿayn, hamza). Because these were typed
by hand over years, the same intended symbol may have been entered as more
than one distinct Unicode code point — e.g. a stray combining mark instead of
a precomposed letter, or a curly quotation mark standing in for a modifier
letter. This script surfaces every non-plain character found inside {...}
spans so those inconsistencies can be spotted and, if needed, normalized
before they leak into transcription prompts or QA tooling.

WHAT IT DOES
------------
1. Parses word/document.xml + word/footnotes.xml of each .docx directly
   (namespace-aware XML parsing — NOT a naive regex on the raw XML, which
   under-matches text split across runs and can be fooled by tags such as
   <w:tab/> or <w:tbl> that merely start with "w:t").
2. Extracts every {...} span per paragraph using a nesting-aware bracket
   scan, and reports any unmatched '{' or '}' as a data-quality warning
   (these indicate typos in the source, e.g. a '}' mistyped as ')').
3. Classifies every non-ASCII / notable character found inside spans into:
     - combining marks (Unicode category Mn/Mc/Me)
     - precomposed letters that carry a diacritic (NFD-decomposable)
     - modifier letters (ʿ ʾ ˈ etc. — includes ʿayn/hamza markers)
     - quotation-mark / apostrophe-family punctuation
     - other special characters
4. Groups diacritic-bearing letters by base letter, so every variant seen
   for the same letter is visible side by side.
5. Auto-flags the one mechanical inconsistency that can be checked without
   linguistic judgement: a combining mark used "bare" (decomposed) on a
   base letter for which the single-codepoint precomposed form is ALSO
   used elsewhere in the corpus for that same combination.
6. For quotation/apostrophe-family characters, splits example occurrences
   into "mid-word" (adjacent to another letter, no space — candidate for
   representing an Arabic sign) vs "prose" (English contractions/quoting),
   since the two are easy to conflate by eye.

Everything else (which of two visually-similar symbols is "correct") is a
judgement call for a human familiar with the transliteration convention —
this script's job is only to make every occurrence, and its context, visible.

USAGE
-----
  python3 audit_ground_truth_unicode.py                  # audits ground-truth/*.docx
  python3 audit_ground_truth_unicode.py file1.docx ...   # audit specific files
  python3 audit_ground_truth_unicode.py --out report.txt
  python3 audit_ground_truth_unicode.py --context 8      # examples shown per character

Standard library only.
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
W_T, W_P, W_TAB, W_BR = W + "t", W + "p", W + "tab", W + "br"

DOCX_PARTS = ("word/document.xml", "word/footnotes.xml")

# Candidate quotation/apostrophe-family code points worth checking for even
# if this corpus turns out not to use them (negative results are useful too).
QUOTE_FAMILY_WATCHLIST = [
    0x0027,  # APOSTROPHE
    0x0060,  # GRAVE ACCENT
    0x00B4,  # ACUTE ACCENT
    0x02B9,  # MODIFIER LETTER PRIME
    0x02BB,  # MODIFIER LETTER TURNED COMMA
    0x02BC,  # MODIFIER LETTER APOSTROPHE
    0x02BD,  # MODIFIER LETTER REVERSED COMMA
    0x02BE,  # MODIFIER LETTER RIGHT HALF RING (hamza)
    0x02BF,  # MODIFIER LETTER LEFT HALF RING (ʿayn)
    0x02C8,  # MODIFIER LETTER VERTICAL LINE
    0x2018,  # LEFT SINGLE QUOTATION MARK
    0x2019,  # RIGHT SINGLE QUOTATION MARK
    0x201B,  # SINGLE HIGH-REVERSED-9 QUOTATION MARK
    0x201C,  # LEFT DOUBLE QUOTATION MARK
    0x201D,  # RIGHT DOUBLE QUOTATION MARK
    0x0022,  # QUOTATION MARK
]


# ---------------------------------------------------------------- extraction

def paragraph_texts(xml_bytes: bytes) -> list[str]:
    """Plain text of every <w:p> in document order, tabs/breaks as whitespace."""
    root = ET.fromstring(xml_bytes)
    out = []
    for p in root.iter(W_P):
        parts = []
        for el in p.iter():
            if el.tag == W_T:
                parts.append(el.text or "")
            elif el.tag == W_TAB:
                parts.append("\t")
            elif el.tag == W_BR:
                parts.append("\n")
        out.append("".join(parts))
    return out


def extract_spans(docx_path: Path) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """
    Returns (spans, warnings).
    spans: list of (docx_filename, span_text) for every matched {...} span
           (all nesting depths — a nested span's text is a substring of its
           parent's, which is fine for character-inventory purposes).
    warnings: list of (docx_filename, message) for unmatched braces.
    """
    spans: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []
    fname = docx_path.name

    with zipfile.ZipFile(docx_path) as z:
        names = set(z.namelist())
        for part in DOCX_PARTS:
            if part not in names:
                continue
            for para in paragraph_texts(z.read(part)):
                depth = 0
                stack_starts: list[int] = []
                for i, ch in enumerate(para):
                    if ch == "{":
                        stack_starts.append(i)
                        depth += 1
                    elif ch == "}":
                        if depth == 0:
                            excerpt = para[max(0, i - 40):i + 10]
                            warnings.append((fname, f"unmatched '}}' near: {excerpt!r}"))
                        else:
                            start = stack_starts.pop()
                            depth -= 1
                            spans.append((fname, para[start + 1:i]))
                if depth != 0:
                    excerpt = para[-80:]
                    warnings.append(
                        (fname, f"unmatched '{{' (still open at paragraph end) near: {excerpt!r}")
                    )
    return spans, warnings


# --------------------------------------------------------------- classification

def nfd_parts(ch: str) -> tuple[str, list[str]]:
    """(base_char, [combining_mark_chars]) via NFD decomposition."""
    decomposed = unicodedata.normalize("NFD", ch)
    if len(decomposed) <= 1:
        return ch, []
    base, marks = decomposed[0], list(decomposed[1:])
    marks = [m for m in marks if unicodedata.category(m) in ("Mn", "Mc", "Me")]
    return base, marks


def mark_label(mark: str) -> str:
    name = unicodedata.name(mark, f"U+{ord(mark):04X}")
    return name.replace("COMBINING ", "")


def classify(ch: str) -> str:
    cp = ord(ch)
    cat = unicodedata.category(ch)
    if cat in ("Mn", "Mc", "Me"):
        return "combining_mark"
    if cat == "Zs":
        return "space"
    if ch.isascii() and (ch.isalnum() or ch in " .,;:!?()/-\n\t&#%\\<>=@\"'`"):
        # plain ASCII letters/digits/common editorial punctuation: not interesting
        if ch in ("'", "`", '"'):
            return "quote_or_apostrophe"
        if ch.isalpha() or ch.isdigit():
            return "plain_ascii"
        return "plain_ascii_punct"
    if cat == "Lm":
        return "modifier_letter"
    if cat in ("Pi", "Pf") or cp in (0x2018, 0x2019, 0x201C, 0x201D, 0x201B):
        return "quote_or_apostrophe"
    if ch.isalpha():
        base, marks = nfd_parts(ch)
        if marks:
            return "precomposed_diacritic_letter"
        return "other_special_letter"
    return "other_symbol"


CONTEXT_WORDCHARS = set("’‘")  # count as part of a "word" for excerpt purposes


def word_span_around(s: str, i: int) -> str:
    start = i
    while start > 0 and (s[start - 1].isalpha() or s[start - 1] in CONTEXT_WORDCHARS):
        start -= 1
    end = i + 1
    while end < len(s) and (s[end].isalpha() or s[end] in CONTEXT_WORDCHARS):
        end += 1
    return s[start:end]


def is_midword_occurrence(s: str, i: int) -> bool:
    prev = s[i - 1] if i > 0 else ""
    nxt = s[i + 1] if i + 1 < len(s) else ""
    if not (prev.isalpha() and nxt.isalpha()):
        return False
    return (ord(prev) > 127) or (ord(nxt) > 127)


# --------------------------------------------------------------------- report

def build_report(spans: list[tuple[str, str]], warnings: list[tuple[str, str]],
                  context_n: int) -> str:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("GROUND-TRUTH UNICODE AUDIT — characters found inside {curly-brace} spans")
    lines.append("=" * 78)
    lines.append(f"\nTotal {{...}} spans scanned: {len(spans)}")

    # ---- data-quality warnings -------------------------------------------
    lines.append("\n" + "-" * 78)
    lines.append(f"UNMATCHED BRACES ({len(warnings)}) — fix these before trusting counts below")
    lines.append("-" * 78)
    if not warnings:
        lines.append("  none")
    else:
        for fname, msg in warnings:
            lines.append(f"  [{fname}] {msg}")

    # ---- per-character inventory -------------------------------------------
    char_count: Counter = Counter()
    char_files: dict[str, set] = defaultdict(set)
    char_examples: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for fname, s in spans:
        for ch in s:
            char_count[ch] += 1
            char_files[ch].add(fname)
            if len(char_examples[ch]) < context_n:
                char_examples[ch].append((fname, s))

    buckets: dict[str, list[str]] = defaultdict(list)
    for ch in char_count:
        buckets[classify(ch)].append(ch)

    def fmt_char_row(ch: str) -> str:
        cp = f"U+{ord(ch):04X}"
        name = unicodedata.name(ch, "<no name>")
        cnt = char_count[ch]
        files = ", ".join(sorted(f.replace(".docx", "") for f in char_files[ch]))
        disp = ch if ch not in ("\n", "\t") else repr(ch)
        return f"  {disp!s:<4} {cp:<10} {name:<48} n={cnt:<5} in: {files}"

    # ---- Section 1: combining marks + precomposed diacritic letters --------
    lines.append("\n" + "=" * 78)
    lines.append("SECTION 1 — COMBINING MARKS & PRECOMPOSED DIACRITIC LETTERS")
    lines.append("=" * 78)

    diacritic_chars = buckets["combining_mark"] + buckets["precomposed_diacritic_letter"]
    grouped: dict[str, list[str]] = defaultdict(list)
    for ch in diacritic_chars:
        if classify(ch) == "combining_mark":
            grouped["(bare combining marks)"].append(ch)
        else:
            base, _ = nfd_parts(ch)
            grouped[base.lower()].append(ch)

    for base in sorted(grouped, key=lambda b: (b == "(bare combining marks)", b)):
        variants = sorted(grouped[base], key=lambda c: -char_count[c])
        lines.append(f"\nBase letter '{base}':" if base != "(bare combining marks)" else "\nBare combining marks (no base letter of their own):")
        for ch in variants:
            if classify(ch) == "combining_mark":
                marks_desc = mark_label(ch)
            else:
                _, marks = nfd_parts(ch)
                marks_desc = "+".join(mark_label(m) for m in marks)
            cp = f"U+{ord(ch):04X}"
            name = unicodedata.name(ch, "<no name>")
            cnt = char_count[ch]
            files = ", ".join(sorted(f.replace(".docx", "") for f in char_files[ch]))
            lines.append(f"  {ch!s:<3} {cp:<10} [{marks_desc:<20}] n={cnt:<5} in: {files}   ({name})")

    # ---- bare-combining-mark attachment + inconsistency auto-flag ---------
    lines.append("\n" + "-" * 78)
    lines.append("Bare combining-mark attachment check")
    lines.append("-" * 78)
    precomposed_in_corpus = set(buckets["precomposed_diacritic_letter"])
    bare_marks = set(buckets["combining_mark"])
    if not bare_marks:
        lines.append("  No bare (standalone) combining marks found — all diacritics are precomposed.")
    for mark in bare_marks:
        attach_counter: Counter = Counter()
        for fname, s in spans:
            for i, ch in enumerate(s):
                if ch == mark and i > 0:
                    attach_counter[s[i - 1]] += 1
        lines.append(f"\n  {mark_label(mark)} (U+{ord(mark):04X}) attaches to:")
        for base_ch, cnt in attach_counter.most_common():
            candidate = unicodedata.normalize("NFC", base_ch + mark)
            flag = ""
            if len(candidate) == 1 and candidate in precomposed_in_corpus:
                flag = (f"  ⚠ INCONSISTENCY: precomposed '{candidate}' (U+{ord(candidate):04X}) "
                        f"for this exact combination is ALSO used elsewhere in the corpus")
            elif len(candidate) == 1:
                flag = f"  (a single precomposed code point '{candidate}' exists in Unicode but is not otherwise used here)"
            else:
                flag = "  (no single precomposed code point exists for this combination — stacking required)"
            lines.append(f"    '{base_ch}' + mark -> {cnt}x{flag}")

    # ---- Section 2: modifier letters + quote/apostrophe family ------------
    lines.append("\n" + "=" * 78)
    lines.append("SECTION 2 — MODIFIER LETTERS (ʿayn/hamza-type) & QUOTATION/APOSTROPHE FAMILY")
    lines.append("=" * 78)
    lines.append(
        "Note on the two counts printed per character below:\n"
        "  'interior' = flanked by two letters with no space, at least one non-ASCII\n"
        "               (e.g. the ʿ in 'Saʿāydih') — the position a modifier letter\n"
        "               normally occupies mid-word, but also where a quote mark\n"
        "               standing in for hamza/ʿayn would show up.\n"
        "  'boundary/other' = word-initial/final or set off by spaces/punctuation.\n"
        "               For ʿ/ʾ this is NORMAL (Arabic words routinely start with\n"
        "               ʿayn or hamza, e.g. 'ʿIliy'). For quote marks (' ' \" \")\n"
        "               this is the EXPECTED bucket — a quote mark showing up in\n"
        "               'interior' position instead is the more surprising case.")

    quote_like = buckets["modifier_letter"] + buckets["quote_or_apostrophe"]
    for ch in sorted(quote_like, key=lambda c: -char_count[c]):
        lines.append("\n" + fmt_char_row(ch))
        midword = 0
        prose = 0
        midword_examples = []
        prose_examples = []
        for fname, s in spans:
            for i, c2 in enumerate(s):
                if c2 == ch:
                    if is_midword_occurrence(s, i):
                        midword += 1
                        if len(midword_examples) < context_n:
                            midword_examples.append((fname, word_span_around(s, i), s))
                    else:
                        prose += 1
                        if len(prose_examples) < context_n:
                            prose_examples.append((fname, s))
        lines.append(f"       interior (letter‖{{ch}}‖letter, non-ASCII neighbor): {midword}   "
                     f"boundary/other: {prose}".replace("{ch}", ch))
        if midword_examples:
            lines.append("       interior examples:")
            for fname, word, s in midword_examples:
                lines.append(f"         [{fname}] {word!r}  <- from: {s[:70]!r}")
        if prose_examples:
            lines.append("       boundary/other examples:")
            for fname, s in prose_examples[:min(3, context_n)]:
                lines.append(f"         [{fname}] {s[:70]!r}")

    lines.append("\n" + "-" * 78)
    lines.append("Watchlist: quote/apostrophe-family code points NOT found in this corpus")
    lines.append("-" * 78)
    found_cps = {ord(c) for c in char_count}
    missing = [cp for cp in QUOTE_FAMILY_WATCHLIST if cp not in found_cps]
    if missing:
        for cp in missing:
            ch = chr(cp)
            lines.append(f"  U+{cp:04X}  {unicodedata.name(ch, '<no name>')}")
    else:
        lines.append("  (all watchlisted code points appear at least once)")

    # ---- Section 3: everything else ----------------------------------------
    other = buckets["other_special_letter"] + buckets["other_symbol"]
    if other:
        lines.append("\n" + "=" * 78)
        lines.append("SECTION 3 — OTHER NON-ASCII / SPECIAL CHARACTERS")
        lines.append("=" * 78)
        for ch in sorted(other, key=lambda c: -char_count[c]):
            lines.append(fmt_char_row(ch))

    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------------ cli

def main(argv=None) -> int:
    BASE = Path(__file__).resolve().parent.parent

    ap = argparse.ArgumentParser(
        description="Audit ground-truth .docx files for diacritic/quotation Unicode inconsistencies.")
    ap.add_argument("inputs", nargs="*", type=Path,
                     help=".docx files to audit (default: all of ground-truth/*.docx)")
    ap.add_argument("--out", type=Path, default=None,
                     help="Save report to this file in addition to printing")
    ap.add_argument("--context", type=int, default=5,
                     help="Number of example spans to show per character/context (default: 5)")
    args = ap.parse_args(argv)

    if args.inputs:
        docx_files = args.inputs
    else:
        docx_files = sorted((BASE / "ground-truth").glob("*.docx"))

    if not docx_files:
        print("No .docx files found.", file=sys.stderr)
        return 1

    all_spans: list[tuple[str, str]] = []
    all_warnings: list[tuple[str, str]] = []
    for f in docx_files:
        spans, warnings = extract_spans(f)
        all_spans.extend(spans)
        all_warnings.extend(warnings)

    report = build_report(all_spans, all_warnings, args.context)
    print(report)

    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"Report saved -> {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
