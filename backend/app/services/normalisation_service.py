import re
from decimal import Decimal
from typing import List, Optional, Set, Tuple

# -----------------------------
# Configurable-rule defaults
# -----------------------------
# These are the *shipped* defaults surfaced by GET /config and applied at import
# when no admin config row exists. They are editorial conventions, not objective
# facts, which is why they're configurable (see normalisation_config.py).

DEFAULT_HONORIFIC_TOKENS: List[str] = [
    "RA",
    "PRA",
    "PPRA",
    "HON",
    "HONRA",
    "ELECT",
    "EX",
    "OFFICIO",
]

# Suppress editions whose total is <= this. 0 = drop only "Edition of 0"
# (today's behaviour). 1 also drops "Edition of 1", which is logically the work
# itself rather than a distinct copy.
DEFAULT_EDITION_SUPPRESS_MAX: int = 0

# Literal find -> replace substitutions applied to the listed derived fields.
# Spaces are significant and preserved, so " - " only matches a spaced hyphen,
# never the hyphen in "double-barrelled".
DEFAULT_TEXT_SUBSTITUTIONS: List[dict] = [
    {"find": "...", "replace": "…", "fields": ["title", "medium"]},
]

# Tokens whose exact casing is preserved when title-casing (acronyms, initialisms,
# stylised names). Matched case-insensitively; the value here is the form emitted.
# Roman numerals are handled separately (by pattern), so they don't go here.
DEFAULT_TITLE_CASE_EXCEPTIONS: List[str] = [
    "RA", "PRA", "PPRA", "RWS", "RE", "NEAC", "OBE", "MBE", "CBE",
    "USA", "UK", "NYC", "LA", "BBC", "MoMA",
]

# Field keys an admin may target, mapped to the Work attribute they normalise.
SUBSTITUTABLE_FIELDS = {
    "title": "title",
    "medium": "medium",
    "artist": "artist_name",
}


# -----------------------------
# Artist
# -----------------------------


def normalise_artist(raw_artist: str, honorific_tokens: Optional[List[str]] = None):
    if not raw_artist:
        return None, None

    artist = str(raw_artist).strip()

    token_set: Set[str] = {
        t.upper()
        for t in (
            honorific_tokens
            if honorific_tokens is not None
            else DEFAULT_HONORIFIC_TOKENS
        )
    }

    parts = artist.split()

    if len(parts) == 1:
        return artist, None

    # Walk backwards collecting recognised honorific tokens
    honorific_parts = []
    i = len(parts) - 1

    while i >= 0 and parts[i].upper() in token_set:
        honorific_parts.insert(0, parts[i])
        i -= 1

    if honorific_parts:
        name = " ".join(parts[: i + 1]).strip()
        honorific = " ".join(honorific_parts).strip()
        return name, honorific

    return artist, None


# -----------------------------
# Price
# -----------------------------


def parse_price(raw_price):
    if raw_price is None:
        return None, "*"

    value = str(raw_price).strip()

    if value == "" or value == "*":
        return None, "*"

    if value.upper() == "NFS":
        return None, "NFS"

    cleaned = re.sub(r"[^0-9.]+", "", value)

    if cleaned == "":
        return None, value

    try:
        numeric = Decimal(cleaned)
        # For v1 tests we return integer pounds and string form without formatting
        integer_value = int(numeric)
        return integer_value, str(integer_value)
    except Exception:
        return None, value


# -----------------------------
# Edition
# -----------------------------


def _parse_edition_components(raw_edition):
    """Parse the raw edition string into ``(total, price)`` without applying any
    suppression. Returns ``(None, None)`` when the string is absent or doesn't
    match the "Edition of N [at £Y]" shape."""
    if not raw_edition:
        return None, None

    value = str(raw_edition).strip()

    full_match = re.match(r"Edition of (\d+) at .*?([0-9,]+\.?[0-9]*)", value)
    if full_match:
        return int(full_match.group(1)), int(
            Decimal(full_match.group(2).replace(",", ""))
        )

    partial_match = re.match(r"Edition of (\d+)", value)
    if partial_match:
        return int(partial_match.group(1)), None

    return None, None


def parse_edition(raw_edition, suppress_max: int = DEFAULT_EDITION_SUPPRESS_MAX):
    """Normalise an edition string to ``(total, price)``.

    Editions whose total is ``<= suppress_max`` are suppressed (returned as
    ``(None, None)``). With the default 0 only "Edition of 0" is dropped; raise
    the threshold to 1 to also drop "Edition of 1" (which is the work itself,
    not a distinct copy). The raw value is never mutated — only the derived
    total/price are withheld — so this stays principle-3 safe.
    """
    total, price = _parse_edition_components(raw_edition)
    if total is None:
        return None, None
    if total <= suppress_max:
        return None, None
    return total, price


# -----------------------------
# Text substitutions
# -----------------------------


def apply_text_substitutions(value, substitutions, field_key: str):
    """Apply each literal find→replace whose ``fields`` includes ``field_key``,
    in list order. Spaces in ``find``/``replace`` are significant. A blank
    ``find`` is skipped (a no-op guard, also enforced at the API).

    When a rule has ``whole_word`` set, the find is wrapped in regex word
    boundaries (``\\b...\\b``) so e.g. ``pla`` → ``PLA`` only matches the
    standalone token and leaves ``plaster`` / ``display`` alone. The find
    is regex-escaped first so any metacharacters in it (``.``, ``(``,
    ``+`` …) are treated as literals; the replace string is also handled
    literally (no backreference parsing) by passing it through a lambda.

    Without ``whole_word`` the rule is a plain substring replace — needed
    by rules whose find is non-alphanumeric (the ``...`` → ``…`` ellipsis
    rule can't use word boundaries because ``.`` isn't a word char on
    either side, so ``\\b...\\b`` would never match)."""
    if not value or not substitutions:
        return value
    out = value
    for sub in substitutions:
        find = (sub or {}).get("find")
        if not find:
            continue
        if field_key not in (sub.get("fields") or []):
            continue
        replace = sub.get("replace", "") or ""
        if sub.get("whole_word"):
            pattern = r"\b" + re.escape(find) + r"\b"
            out = re.sub(pattern, lambda _m, r=replace: r, out)
        else:
            out = out.replace(find, replace)
    return out


# -----------------------------
# Title casing
# -----------------------------

# Strict Roman numeral (II, IV, VIII, XIV …). Single letters are excluded by the
# length guard in the callback ("I" is handled by titlecase itself).
_ROMAN_RE = re.compile(
    r"^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$", re.IGNORECASE
)
# Common words / short forms that match the Roman pattern but usually aren't
# numerals — left as ordinary title-cased words (still override-correctable).
_ROMAN_DENYLIST = {"mix", "di", "li", "mm", "cd", "mi", "dc"}


def _looks_roman(core: str) -> bool:
    return (
        len(core) > 1
        and core.lower() not in _ROMAN_DENYLIST
        and bool(_ROMAN_RE.match(core))
    )


def _title_token_reason(word: str, canon: dict) -> Tuple[str, Optional[str]]:
    """Classify a single word for title-casing.

    Returns ``(core, reason)`` where ``core`` is the word stripped of leading/
    trailing punctuation and ``reason`` is ``"exception"`` (matched the curated
    exceptions list), ``"roman_numeral"`` (matched the Roman pattern), or
    ``None`` (no rule applies — let titlecase decide). ``canon`` maps an
    upper-cased exception to its emitted form.

    Single source of truth shared by :func:`to_title_case` (which acts on the
    result) and :func:`title_case_preserved_tokens` (which reports it), so the
    two can never drift.
    """
    core = re.sub(r"^[^0-9A-Za-z]+|[^0-9A-Za-z]+$", "", word)
    if not core:
        return "", None
    if core.upper() in canon:
        return core, "exception"
    if _looks_roman(core):
        return core, "roman_numeral"
    return core, None


def title_case_preserved_tokens(
    text, exceptions: Optional[List[str]] = None
) -> List[Tuple[str, str]]:
    """Tokens that :func:`to_title_case` keeps uppercase, as ``(token, reason)``.

    ``reason`` is ``"exception"`` or ``"roman_numeral"``. Order-preserving and
    de-duplicated within the string. Used to flag potential false positives
    (a real word matching the Roman pattern, or a stray exception hit like the
    article "la" matching an "LA" exception) without re-implementing the rule.
    """
    if not text:
        return []
    canon = {e.upper(): e for e in (exceptions or []) if e}
    out: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    for word in str(text).split():
        core, reason = _title_token_reason(word, canon)
        if reason and core.upper() not in seen:
            seen.add(core.upper())
            display = canon[core.upper()] if reason == "exception" else core.upper()
            out.append((display, reason))
    return out


def to_title_case(text, exceptions: Optional[List[str]] = None):
    """Best-effort Title Case for a display string.

    Uses the ``titlecase`` library (Gruber's algorithm: small words like "of",
    "the" stay lower). All-caps input is cased correctly; intentional mixed case
    (e.g. "iPhone") is preserved. A callback restores two things the algorithm
    can't infer from cased-away input:

      - exact-cased *exceptions* (acronyms / initialisms / stylised names), and
      - multi-letter Roman numerals (uppercased).

    Lossy by nature for all-caps input — the result is meant to be reviewed and
    corrected per work via the title-case override.
    """
    if not text:
        return text

    from titlecase import titlecase  # local import: optional-feature dependency

    canon = {e.upper(): e for e in (exceptions or []) if e}

    def _callback(word, **kwargs):
        core, reason = _title_token_reason(word, canon)
        if reason == "exception":
            return word.replace(core, canon[core.upper()])
        if reason == "roman_numeral":
            return word.replace(core, core.upper())
        return None  # let titlecase decide

    return titlecase(text, callback=_callback)


# -----------------------------
# Work Normalisation
# -----------------------------


def normalise_work(
    work,
    honorific_tokens: Optional[List[str]] = None,
    edition_suppress_max: int = DEFAULT_EDITION_SUPPRESS_MAX,
    text_substitutions: Optional[List[dict]] = None,
    title_case_exceptions: Optional[List[str]] = None,
):
    """Compute a Work's derived fields from its raw_* fields.

    Configurable editorial rules (honorific tokens, edition suppression
    threshold, literal text substitutions, title-case exceptions) are applied
    here. Only derived fields are written; raw_* values are left canonical
    (principle 3).
    """
    work.artist_name, work.artist_honorifics = normalise_artist(
        work.raw_artist, honorific_tokens
    )
    work.price_numeric, work.price_text = parse_price(work.raw_price)
    work.edition_total, work.edition_price_numeric = parse_edition(
        work.raw_edition, suppress_max=edition_suppress_max
    )

    if work.raw_artwork:
        try:
            work.artwork = int(str(work.raw_artwork).strip())
        except (ValueError, TypeError):
            work.artwork = None

    if work.raw_title:
        work.title = str(work.raw_title).strip()

    if work.raw_medium:
        work.medium = str(work.raw_medium).strip()

    # Literal text substitutions, applied last to the derived fields so they act
    # on the trimmed values an admin actually sees.
    if text_substitutions:
        for field_key, attr in SUBSTITUTABLE_FIELDS.items():
            current = getattr(work, attr, None)
            if current:
                setattr(
                    work,
                    attr,
                    apply_text_substitutions(current, text_substitutions, field_key),
                )

    # Derived Title Case form, alongside the (possibly all-caps) title. Best
    # effort — corrected per work via the title-case override, used by outputs
    # like the LPG that want title case rather than the LOW's house caps.
    exceptions = (
        title_case_exceptions
        if title_case_exceptions is not None
        else DEFAULT_TITLE_CASE_EXCEPTIONS
    )
    work.title_cased = to_title_case(work.title, exceptions) if work.title else None


# -----------------------------
# Validation Warnings
# -----------------------------


def collect_work_warnings(
    work,
    edition_suppress_max: int = DEFAULT_EDITION_SUPPRESS_MAX,
    title_case_exceptions: Optional[List[str]] = None,
) -> List[Tuple[str, str]]:
    """
    Inspect a normalised Work and return a list of (warning_type, message) tuples.
    Must be called after normalise_work() with the *same* edition_suppress_max
    and title_case_exceptions.

    Warning types:
      whitespace_trimmed     – leading/trailing whitespace removed from fields
      missing_title          – no title after normalisation
      missing_artist         – no artist name after normalisation
      missing_price          – price is blank/placeholder (*)
      unrecognised_price     – raw price present but could not be parsed
      edition_anomaly        – raw edition present but could not be parsed
      zero_edition_suppressed – edition was explicitly of 0 (suppressed)
      edition_suppressed      – edition of 1..threshold suppressed (the work itself)
      edition_suppressed_no_price – HIGH: a suppressed edition was the work's only
                                price; its value should be restored via an override
      non_ascii_characters    – normalised fields contain chars outside ASCII-128
      title_case_roman        – title-casing kept a token uppercase as a Roman
                                numeral (review: it might be a real word)
      title_case_exception    – title-casing kept a token uppercase via the
                                exceptions list (review for false positives)
    """
    warnings: List[Tuple[str, str]] = []

    # Whitespace trimming — flag fields where raw != normalised only due to whitespace
    _ws_fields = [
        ("Title", getattr(work, "raw_title", None), getattr(work, "title", None)),
        ("Artist", getattr(work, "raw_artist", None), getattr(work, "artist_name", None)),
        ("Medium", getattr(work, "raw_medium", None), getattr(work, "medium", None)),
    ]
    trimmed_fields = []
    for label, raw_val, norm_val in _ws_fields:
        rv = str(raw_val) if raw_val is not None else ""
        nv = str(norm_val) if norm_val is not None else ""
        if rv != nv and rv.strip() == nv:
            trimmed_fields.append(label)
    if trimmed_fields:
        warnings.append(
            (
                "whitespace_trimmed",
                f"Whitespace trimmed from {', '.join(trimmed_fields)}",
            )
        )

    # Missing title
    if not work.title:
        warnings.append(("missing_title", "Work has no title"))

    # Missing artist
    if not work.artist_name:
        warnings.append(("missing_artist", "Work has no artist name"))

    # Missing price (blank or placeholder)
    if work.price_numeric is None and work.price_text == "*":
        warnings.append(("missing_price", "Price is blank or placeholder"))

    # Unrecognised price – raw value present but not mapped to numeric, NFS, or *
    if work.raw_price:
        raw_p = str(work.raw_price).strip()
        if (
            raw_p
            and raw_p.upper() not in ("NFS", "*", "")
            and work.price_numeric is None
            and work.price_text not in ("NFS", "*", None, "")
        ):
            warnings.append(
                ("unrecognised_price", f"Price could not be parsed: {raw_p!r}")
            )

    # Edition handling — re-derive the original components (ignoring suppression)
    # so we can explain what happened and flag the dangerous case.
    if work.raw_edition:
        raw_ed = str(work.raw_edition).strip()
        if raw_ed:
            total, ed_price = _parse_edition_components(raw_ed)
            if total is None:
                # Couldn't parse it at all → anomaly.
                warnings.append(
                    (
                        "edition_anomaly",
                        f"Edition field could not be parsed: {raw_ed!r}",
                    )
                )
            elif total <= edition_suppress_max:
                # Suppressed by the threshold.
                no_work_price = work.price_numeric is None and getattr(
                    work, "price_text", None
                ) in (None, "", "*")
                if total == 0:
                    # "Edition of 0" — there is no edition; benign.
                    warnings.append(
                        (
                            "zero_edition_suppressed",
                            f"Zero edition suppressed: {raw_ed!r}",
                        )
                    )
                elif ed_price is not None and no_work_price:
                    # An "edition of 1" with a price IS the work's price, and the
                    # work has no price of its own — suppressing it would lose the
                    # only price. Surface loudly so it's restored via an override.
                    warnings.append(
                        (
                            "edition_suppressed_no_price",
                            f"{raw_ed!r} suppressed, removing the only price "
                            f"(£{ed_price}). Set the work price via an override.",
                        )
                    )
                else:
                    # Suppressed, but the work keeps its own price — benign.
                    warnings.append(
                        (
                            "edition_suppressed",
                            f"Edition suppressed (treated as the work itself): "
                            f"{raw_ed!r}",
                        )
                    )

    # Non-ASCII characters – will be unicode-escaped in the InDesign export
    _non_ascii_fields = {
        "title": getattr(work, "title", None),
        "artist": getattr(work, "artist_name", None),
        "honorifics": getattr(work, "artist_honorifics", None),
        "medium": getattr(work, "medium", None),
    }
    non_ascii_hits = []
    for field_name, value in _non_ascii_fields.items():
        if not value:
            continue
        chars = sorted({ch for ch in value if ord(ch) > 127}, key=ord)
        if chars:
            samples = ", ".join(f"{ch!r} (U+{ord(ch):04X})" for ch in chars[:5])
            non_ascii_hits.append(f"{field_name}: {samples}")
    if non_ascii_hits:
        warnings.append(
            (
                "non_ascii_characters",
                "Non-ASCII characters will be unicode-escaped in export — "
                + "; ".join(non_ascii_hits),
            )
        )

    # Title-case preservations — tokens the title-casing rule kept uppercase in
    # the derived title_cased field. Surfaced (split by reason) so staff can spot
    # false positives: a real word that matched the Roman-numeral pattern, or a
    # stray exceptions-list hit such as the article "la" matching an "LA" entry.
    if getattr(work, "title", None):
        tc_exceptions = (
            title_case_exceptions
            if title_case_exceptions is not None
            else DEFAULT_TITLE_CASE_EXCEPTIONS
        )
        preserved = title_case_preserved_tokens(work.title, tc_exceptions)
        roman = [t for t, r in preserved if r == "roman_numeral"]
        exc = [t for t, r in preserved if r == "exception"]
        if roman:
            warnings.append(
                (
                    "title_case_roman",
                    "Title case kept as a Roman numeral: "
                    + ", ".join(roman)
                    + " — review in case it is a word.",
                )
            )
        if exc:
            warnings.append(
                (
                    "title_case_exception",
                    "Title case kept uppercase via the exceptions list: "
                    + ", ".join(exc)
                    + " — review for false positives.",
                )
            )

    return warnings
