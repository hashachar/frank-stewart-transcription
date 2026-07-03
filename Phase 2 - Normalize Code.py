#!/usr/bin/env python3
"""
stewart_normalize.py — Step 2 of the Frank Stewart fieldnotes pipeline.

Converts the INTERIM NOTATION emitted by the Step 1 reader pass into final
Unicode, producing TWO parallel versions of every input:

  1. LITERAL     — renders each mark as the glyph that is physically on the
                   page (line *over* d, s/S-with-acute, theta, the original
                   quote marks). Faithful to what Stewart typed; useful for
                   eyeball verification against the scan.

  2. NORMALIZED  — applies every conversion specified in the guideline PDFs
                   (line-over-d -> line-under-d, s/S-acute -> š/Š,
                   the "O"/theta symbol -> ṯ, ayn -> ʿ, hamza -> ʾ). The
                   scholarly, searchable output.

Both versions are derived from the SAME interim text, so they stay aligned.

----------------------------------------------------------------------------
INTERIM NOTATION
----------------------------------------------------------------------------
A marked letter is written   BASE{mark1,mark2,...}   where BASE is one letter
(case-significant). A handful of graphemes have no base and are written as
standalone tokens, e.g. {apostrophe-ayn}.

  interim code              page form                LITERAL      NORMALIZED   guideline
  -------------------------  ----------------------   ----------   ----------   ---------
  X{dotbelow}                dot under a letter       ḥ ṣ ṭ ṛ …   ḥ ṣ ṭ ṛ …   rule 1
  V{macron}                  line over a vowel        ā ī ē ū     ā ī ē ū     rule 2
  d{macron}                  line over d              d̄           ḏ           rule 3
  D{macron}                  line over D              D̄           Ḏ           rule 3
  d{macron,dotbelow}         line over d + dot under  ḍ̄           ḏ̣           rule 4
  D{macron,dotbelow}         line over D + dot under  Ḍ̄           Ḏ̣           rule 4
  s{acute}                   s with acute             ś            š           rule 5 (lower)
  S{acute}                   S with acute             Ś            Š           rule 5 (upper)
  X{dotabove}                dot over a letter        ġ Ġ          ġ Ġ         (census-found)
  a{acute} i{acute} u{acute} acute on a vowel         á í ú        á í ú       (acute accent)
  S{cedilla}                 letter with cedilla      Ş            Ş           (cedilla)
  a{macron}{cedilla}         macron + cedilla         ā̧          ā̧         (stacked)
  {theta-symbol}             the "O" / θ symbol       θ            ṯ           rule 6
  {apostrophe-ayn}           opening quote ‘     ‘            ʿ (U+02BF)  rule 7
  {apostrophe-hamza}         hamza quote ’       ʼ            ʾ (U+02BE)  rule 8

Structural markers are also supported in both LITERAL and NORMALIZED output:

  interim code              output
  -------------------------  -----------------------------------------------
  {HEADING}text{/HEADING}    **text**   (Markdown bold)
  {LB}                       one literal newline (\n)
  {INDENT}                   INDENTATION, default four spaces

  # {apostrophe-ayn} and {apostrophe-hamza} are two DISTINCT printed quote
  # marks (‘ U+2018, ’ U+2019), never inferred from word context:
  # Step 1 identifies the glyph, Step 2 maps ayn -> ʿ (U+02BF) and
  # hamza -> ʾ (U+02BE) in NORMALIZED output.

Notes
-----
* d{macron} and D{macron} use the same {macron} token as vowels, but in
  NORMALIZED output they map to combining macron BELOW (U+0331 → ḏ/Ḏ)
  via the profile's base_overrides table. On all other bases {macron}
  stays as combining macron above (U+0304).
* Stacked marks render macron-first, dotbelow-second: d{macron,dotbelow}
  -> line directly under d, dot under the line (rule 4).
* ayn and hamza are caseless; every other grapheme preserves case.
* Anything the module cannot map is LEFT LITERAL and FLAGGED — it never
  silently drops or "fixes" a token.

----------------------------------------------------------------------------
OUTPUT FILES (per input file `X.txt`, sitting in a Phase-1 config folder
like "gpt-5.5_effort-high_CI-on")
----------------------------------------------------------------------------
  X.<config>.literal.txt      UTF-8 plain text — the literal version
  X.<config>.normalized.txt   UTF-8 plain text — the normalized version
  X.<config>.report.json      flags + provenance + symbol counts (sidecar)

  <config> is the name of the input file's parent folder, carried into the
  filename so outputs stay traceable to their source config once moved.

Why these formats: plain UTF-8 text is the most portable, future-proof,
searchable, diff-able, and Word-importable container for the transcription
itself; the JSON sidecar keeps machine-readable QA metadata out of the prose.

----------------------------------------------------------------------------
EXTENDING THIS FILE
----------------------------------------------------------------------------
Everything that defines behaviour lives in the PROFILES and RENDER_ORDER
tables below — add a symbol or change a target by editing data, not logic.
To add a whole new output variant, define another Profile and list it in
PROFILES. The engine never needs to change.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MODULE_VERSION = "2.4"

# Structural-marker rendering. Change this one variable if a different
# indentation string is needed throughout both literal and normalized output.
INDENTATION = "    "

# Emission order for stacked marks, keyed by mark NAME. Marks of equal Unicode
# combining class are not reordered by normalization, so we must place the
# macron before dotbelow ourselves (critical for d{macron,dotbelow} → ḏ̣).
RENDER_ORDER = {
    "macron":   0,
    "dotbelow": 1,
    "dotabove": 2,
    "acute":    3,
    "cedilla":  4,   # below the base, like dotbelow; ordered after macron
}


@dataclass(frozen=True)
class Profile:
    """A complete mapping from interim notation to output Unicode."""
    name: str
    marks: dict          # mark name  -> combining string appended to the base
    standalone: dict     # token name -> standalone output string
    allowed_base: dict   # mark name  -> set of base letters it may attach to
    base_overrides: dict = field(default_factory=dict)  # (base_lower, mark) -> combining str
    form: str = "NFC"    # Unicode normalization form for the output


# --- the conversions the PDF asks for: line-under-d, carons, ṯ, half-rings ---
NORMALIZED = Profile(
    name="normalized",
    marks={
        "dotbelow": "̣",   # combining dot below
        "macron":   "̄",   # combining macron above (vowels); overridden for d/D below
        "dotabove": "̇",   # combining dot above
        "acute":    "̌",   # s/S-acute denotes shin -> caron -> š/Š
        "cedilla":  "\u0327",   # combining cedilla (U+0327)
    },
    standalone={
        "apostrophe-ayn":          "\u02bf",   # U+02BF modifier letter left half ring  (page: \u2018)
        "apostrophe-hamza":        "\u02be",   # U+02BE modifier letter right half ring (page: \u2019)
        "theta-symbol":     "ṯ",      # ṯ  t with line below
    },
    allowed_base={
        "acute": set("sSaiu"),
    },
    base_overrides={
        ("d", "macron"): "̱",   # d{macron}/D{macron} -> ḏ/Ḏ  (line below, not above)
        # Acute on a vowel is a genuine acute accent, not the shin caron.
        ("a", "acute"): "\u0301",   # combining acute (U+0301)
        ("i", "acute"): "\u0301",
        ("u", "acute"): "\u0301",
    },
)

# --- faithful to the page: line-over-d, ś, Ś, θ, original quote marks ----------
LITERAL = Profile(
    name="literal",
    marks={
        "dotbelow": "̣",   # same as normalized
        "macron":   "̄",   # combining macron above — vowels AND d/D (faithful to page)
        "dotabove": "̇",   # same as normalized
        "acute":    "́",   # literal acute -> ś / Ś
        "cedilla":  "\u0327",   # combining cedilla (U+0327)
    },
    standalone={
        # The guideline describes ayn as an opening quote ' and hamza as a
        # vertical quote '. Kept distinct here so no information is lost.
        # Change these two lines if you would rather see ʿ / ʾ in both versions.
        "apostrophe-ayn":          "\u2018",   # U+2018 left single quotation mark   (page glyph as printed)
        "apostrophe-hamza":        "\u02bc",        # U+02BC modifier letter apostrophe (vertical, as before)
        "theta-symbol":     "θ",       # θ  greek small letter theta
    },
    allowed_base={
        "acute": set("sSaiu"),
    },
)

PROFILES = [LITERAL, NORMALIZED]

# One optional base letter directly followed by one or more adjacent {...} groups.
# This supports both:
#   d{macron,dotbelow}   # comma-stacked notation
#   d{macron}{dotbelow}  # adjacent-token stacked notation
_TOKEN = re.compile(r"([A-Za-z])?((?:\{[^{}]*\})+)")
_GROUP = re.compile(r"\{([^{}]*)\}")


def _apply_structural_markers(text: str) -> str:
    """Render hard-coded structural markers before diacritic token handling."""
    # Convert complete heading spans first, leaving enclosed interim notation
    # intact so the normal profile-specific pass can still render diacritics.
    text = re.sub(r"\{HEADING\}(.*?)\{/HEADING\}", r"**\1**", text, flags=re.DOTALL)

    # Every {LB} is exactly one newline. Because this is a direct replacement,
    # consecutive markers naturally become consecutive newlines.
    text = text.replace("{LB}", "\n")

    # Centralized indentation string, configurable through INDENTATION above.
    text = text.replace("{INDENT}", INDENTATION)
    return text


def _build(base: str, marks: list[str], profile: Profile) -> str:
    """base + ordered combining marks for a list of validated mark names."""
    ordered = sorted(marks, key=lambda m: RENDER_ORDER.get(m, 99))
    result = base
    for m in ordered:
        key = (base.lower(), m)
        result += profile.base_overrides.get(key, profile.marks[m])
    return result


def _apply(text: str, profile: Profile, form: str | None = None,
           flags: list | None = None, counts: Counter | None = None) -> str:
    """
    Apply one profile to `text`. If `flags`/`counts` are given they are filled
    in (do this once, on a single profile, to avoid duplicate reports).
    """
    record = flags is not None
    text = _apply_structural_markers(text)
    matches = list(_TOKEN.finditer(text))

    def repl(m: re.Match) -> str:
        base, groups = m.group(1), m.group(2)
        token, pos = m.group(0), m.start()

        contents = _GROUP.findall(groups)

        # Standalone grapheme with no base, e.g. {theta-symbol}.
        if base is None and len(contents) == 1 and contents[0] in profile.standalone:
            if counts is not None:
                counts[contents[0]] += 1
            return profile.standalone[contents[0]]

        # Base + standalone grapheme, e.g. a{apostrophe-ayn} -> aʿ.
        if base is not None and len(contents) == 1 and contents[0] in profile.standalone:
            if counts is not None:
                counts[contents[0]] += 1
            return base + profile.standalone[contents[0]]

        # Base + mark(s), optionally followed by one standalone token.
        # This preserves valid forms like mi{macron}{apostrophe-ayn}a{macron}d
        # while also accepting stacked adjacent marks like d{macron}{dotbelow}.
        trailing_standalone = None
        mark_contents = contents
        if contents and contents[-1] in profile.standalone:
            trailing_standalone = contents[-1]
            mark_contents = contents[:-1]

        mark_list: list[str] = []
        for content in mark_contents:
            mark_list.extend([p for p in content.split(",") if p])

        unknown = [p for p in mark_list if p not in profile.marks]
        if unknown or not mark_list:
            if record:
                flags.append({"type": "unknown-token", "token": token,
                              "position": pos,
                              "note": f"unrecognized: {unknown or contents!r}"})
            return token
        if base is None:
            if record:
                flags.append({"type": "orphan-mark", "token": token,
                              "position": pos, "note": "mark group has no base letter"})
            return token
        for mk in mark_list:
            allowed = profile.allowed_base.get(mk)
            if allowed is not None and base not in allowed:
                if record:
                    flags.append({"type": "mark-on-unexpected-base", "token": token,
                                  "position": pos,
                                  "note": f"'{mk}' not defined for base '{base}'"})
                return token  # keep literal for human review

        if counts is not None:
            for mk in mark_list:
                counts[mk] += 1
            if trailing_standalone is not None:
                counts[trailing_standalone] += 1

        built = _build(base, mark_list, profile)
        if trailing_standalone is not None:
            built += profile.standalone[trailing_standalone]
        return built

    out = _TOKEN.sub(repl, text)

    # Braces in the original text not covered by any token match are malformed.
    if record:
        covered = [(m.start(), m.end()) for m in matches]
        for bm in re.finditer(r"[{}]", text):
            i = bm.start()
            if not any(s <= i < e for s, e in covered):
                flags.append({"type": "stray-brace", "token": bm.group(0),
                              "position": i,
                              "note": "unmatched brace; check Step-1 output"})

    return unicodedata.normalize(form or profile.form, out)


def convert(text: str, form: str = "NFC"):
    """
    Convert interim `text` to all profiles.

    Returns (versions, flags, counts) where `versions` maps profile name ->
    output string. Flags/counts are computed once on the NORMALIZED profile
    (mark names and base rules are shared across profiles).
    """
    flags: list = []
    counts: Counter = Counter()
    versions = {}
    for prof in PROFILES:
        if prof is NORMALIZED:
            versions[prof.name] = _apply(text, prof, form=form, flags=flags, counts=counts)
        else:
            versions[prof.name] = _apply(text, prof, form=form)
    return versions, flags, counts


def process_file(in_path: Path, outdir: Path | None = None, form: str = "NFC") -> dict:
    """Normalize one file; write <stem>.<profile>.txt and <stem>.report.json."""
    in_path = Path(in_path)
    outdir = Path(outdir) if outdir else in_path.parent
    outdir.mkdir(parents=True, exist_ok=True)

    text = in_path.read_text(encoding="utf-8")
    versions, flags, counts = convert(text, form=form)

    stem = in_path.stem
    # Config tag = the input file's parent folder name, e.g. Phase 1's
    # auto-named "gpt-5.5_effort-high_CI-on" output subfolder. Carrying it
    # into the filename keeps files traceable once copied out of that folder.
    config_tag = in_path.resolve().parent.name
    base_name = f"{stem}.{config_tag}"
    written = []
    for name, out in versions.items():
        p = outdir / f"{base_name}.{name}.txt"
        p.write_text(out, encoding="utf-8")
        written.append(str(p))

    report = {
        "source": str(in_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "module_version": MODULE_VERSION,
        "unicode_form": form,
        "profiles": [p.name for p in PROFILES],
        "symbol_counts": dict(sorted(counts.items())),
        "n_flags": len(flags),
        "flags": flags,
        "outputs": written,
    }
    report_path = outdir / f"{base_name}.report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# Self-test: cases drawn from the actual documents and the notation table.
# ---------------------------------------------------------------------------
def _selftest() -> int:
    nfc = lambda s: unicodedata.normalize("NFC", s)
    # (interim, expected_literal, expected_normalized)
    cases = [
        # rule 5: s/S with acute
        ("s{acute}e{macron}x",               "śēx",       "šēx"),      # śēx / šēx
        ("S{acute}awwa",                     "Śawwa",          "Šawwa"),          # Śawwa / Šawwa
        # rule 1: dot below
        ("H{dotbelow}amada{macron}t",        "Ḥamadāt",    "Ḥamadāt"),    # Ḥamadāt
        ("r{dotbelow}amala",                 "ṛamala",         "ṛamala"),         # ṛamala
        ("R{dotbelow}amala",                 "Ṛamala",         "Ṛamala"),         # Ṛamala
        # rule 3: line over d (same token as vowel macron, different NORMALIZED output)
        ("al-Ad{macron}aydiy",               nfc("al-Ad̄aydiy"), "al-Aḏaydiy"),    # al-Ad̄.. / al-Aḏ..
        ("al-AD{macron}aydiy",               nfc("al-AD̄aydiy"), "al-AḎaydiy"),    # al-AD̄.. / al-AḎ..
        # rule 4: stacked macron + dotbelow
        ("rad{macron,dotbelow}d{macron,dotbelow}awha",
                                             nfc("raḍ̄ḍ̄awha"),         # raḍ̄ḍ̄awha
                                             "raḏ̣ḏ̣awha"),               # raḏ̣ḏ̣awha
        ("rad{macron}{dotbelow}d{macron}{dotbelow}awha",
                                             nfc("raḍ̄ḍ̄awha"),         # adjacent-token stacked notation
                                             "raḏ̣ḏ̣awha"),
        ("al-D{macron,dotbelow}aydiy",       nfc("al-Ḍ̄aydiy"),
                                             "al-Ḏ̣aydiy"),                         # al-Ḏ̣aydiy
        ("al-D{macron}{dotbelow}aydiy",      nfc("al-Ḍ̄aydiy"),
                                             "al-Ḏ̣aydiy"),                         # adjacent-token stacked notation
        # rule 2: macron on vowels (unchanged in both profiles)
        ("Rm{dotbelow}a{macron}g",           "Rṃāg",       "Rṃāg"),      # Rṃāg
        ("xa{macron}l{dotbelow}",            "xāḷ",        "xāḷ"),        # xāḷ
        ("T{dotbelow}a{macron}ygih",         "Ṭāygih",     "Ṭāygih"),    # Ṭāygih
        ("T{dotbelow}a{macron}rif",          "Ṭārif",      "Ṭārif"),     # Ṭārif
        # rule 7: ayn
        ("{apostrophe-ayn}Awdih",            "‘Awdih",          "ʿAwdih"),
        ("ma{apostrophe-ayn}a",              "ma‘a",            "maʿa"),
        # rule 8: hamza -> ʾ (U+02BE) normalized; literal ʼ (U+02BC)
        ("ra{apostrophe-hamza}iy",                      "ra\u02bciy",      "ra\u02beiy"),
        # acute on vowels stays acute (á/í/ú) in BOTH profiles, never caron
        ("a{acute}i{acute}u{acute}",         "\u00e1\u00ed\u00fa", "\u00e1\u00ed\u00fa"),
        # cedilla: Ş = S{cedilla}, and stacked macron + cedilla
        ("S{cedilla}alih",                   nfc("S\u0327alih"), nfc("S\u0327alih")),
        ("a{macron}{cedilla}b",              nfc("a\u0304\u0327b"), nfc("a\u0304\u0327b")),
        # rule 6: theta-symbol
        ("{theta-symbol}",                   "θ",               "ṯ"),
        # dotabove
        ("g{dotabove}adab",                  "ġadab",           "ġadab"),
        # structural markers: heading, line break, and configurable indentation
        ("{HEADING}Sa{macron}lim{/HEADING}", "**Sālim**", "**Sālim**"),
        ("a{LB}{LB}b",                       "a\n\nb",             "a\n\nb"),
        ("{INDENT}s{acute}e{macron}x",       INDENTATION + "śēx",    INDENTATION + "šēx"),
        ("x{LB}{INDENT}y",                   "x\n" + INDENTATION + "y", "x\n" + INDENTATION + "y"),
        # plain text unchanged
        ("byh{dotbelow}ut{dotbelow}t{dotbelow}uw", "byḥuṭṭuw", "byḥuṭṭuw"),
        ("lahad",                            "lahad",                "lahad"),
    ]
    ok = True
    print(f"{'STATUS':6} {'INTERIM':50} {'LITERAL':14} {'NORMALIZED'}")
    for src, wlit, wnorm in cases:
        versions, _, _ = convert(src)
        glit, gnorm = versions["literal"], versions["normalized"]
        good = glit == nfc(wlit) and gnorm == nfc(wnorm)
        ok = ok and good
        print(f"{'ok' if good else 'FAIL':6} {src!r:50} {glit!r:14} {gnorm!r}")

    print("\nflagging (each should raise a flag, output kept literal):")
    for src in ["x{wiggle}", "{dotbelow}", "k{acute}", "a{macron"]:
        versions, flags, _ = convert(src)
        print(f"  {src!r:14} -> {versions['normalized']!r:14} flags={[f['type'] for f in flags]}")

    print("\ncounts demo:", dict(convert("s{acute}e{macron}x and {apostrophe-ayn}Awdih")[2]))
    print("\nALL CASES PASS" if ok else "\nSOME CASES FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Step 2 normalization: interim notation -> literal + normalized Unicode.")
    ap.add_argument("inputs", nargs="*", type=Path,
                    help="interim-notation .txt files to convert")
    ap.add_argument("--outdir", type=Path, default=None,
                    help="output directory (default: alongside each input)")
    ap.add_argument("--form", default="NFC", choices=["NFC", "NFD"],
                    help="Unicode normalization form (default NFC)")
    ap.add_argument("--selftest", action="store_true",
                    help="run built-in checks and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.inputs:
        ap.print_help()
        return 1
    for path in args.inputs:
        report = process_file(path, outdir=args.outdir, form=args.form)
        print(f"{path}: {report['n_flags']} flag(s); wrote "
              f"{', '.join(Path(o).name for o in report['outputs'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
