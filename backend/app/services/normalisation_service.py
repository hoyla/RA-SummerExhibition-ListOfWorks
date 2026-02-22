import re
from decimal import Decimal
from typing import List, Optional, Set, Tuple


# -----------------------------
# Artist
# -----------------------------

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


def parse_edition(raw_edition):
    if not raw_edition:
        return None, None

    value = str(raw_edition).strip()

    if value.startswith("Edition of 0"):
        return None, None

    full_match = re.match(r"Edition of (\d+) at .*?([0-9,]+\.?[0-9]*)", value)
    if full_match:
        total = int(full_match.group(1))
        price = int(Decimal(full_match.group(2).replace(",", "")))
        return total, price

    partial_match = re.match(r"Edition of (\d+)", value)
    if partial_match:
        total = int(partial_match.group(1))
        return total, None

    return None, None


# -----------------------------
# Work Normalisation
# -----------------------------


def normalise_work(work, honorific_tokens: Optional[List[str]] = None):
    work.artist_name, work.artist_honorifics = normalise_artist(
        work.raw_artist, honorific_tokens
    )
    work.price_numeric, work.price_text = parse_price(work.raw_price)
    work.edition_total, work.edition_price_numeric = parse_edition(work.raw_edition)

    if work.raw_artwork:
        try:
            work.artwork = int(str(work.raw_artwork).strip())
        except (ValueError, TypeError):
            work.artwork = None

    if work.raw_title:
        work.title = str(work.raw_title).strip()

    if work.raw_medium:
        work.medium = str(work.raw_medium).strip()


# -----------------------------
# Validation Warnings
# -----------------------------


def collect_work_warnings(work) -> List[Tuple[str, str]]:
    """
    Inspect a normalised Work and return a list of (warning_type, message) tuples.
    Must be called after normalise_work().

    Warning types:
      missing_title          – no title after normalisation
      missing_artist         – no artist name after normalisation
      missing_price          – price is blank/placeholder (*)
      unrecognised_price     – raw price present but could not be parsed
      edition_anomaly        – raw edition present but could not be parsed
      zero_edition_suppressed – edition was explicitly of 0 (suppressed)
      non_ascii_characters    – normalised fields contain chars outside ASCII-128
    """
    warnings: List[Tuple[str, str]] = []

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

    # Edition handling
    if work.raw_edition:
        raw_ed = str(work.raw_edition).strip()
        if raw_ed:
            # Zero edition suppressed
            if re.match(r"edition of 0", raw_ed, re.IGNORECASE):
                warnings.append(
                    (
                        "zero_edition_suppressed",
                        f"Zero edition suppressed: {raw_ed!r}",
                    )
                )
            # Anomaly: non-zero edition content that could not be parsed
            elif work.edition_total is None:
                warnings.append(
                    (
                        "edition_anomaly",
                        f"Edition field could not be parsed: {raw_ed!r}",
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

    return warnings
