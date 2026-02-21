import re
from decimal import Decimal


# -----------------------------
# Artist
# -----------------------------


def normalise_artist(raw_artist: str):
    if not raw_artist:
        return None, None

    artist = str(raw_artist).strip()

    parts = artist.split()

    # Simple honorific detection:
    # If last token is all caps (e.g. RA, PRA, PPRA)
    if len(parts) > 1 and parts[-1].isupper() and len(parts[-1]) <= 6:
        honorific = parts[-1]
        name = " ".join(parts[:-1])
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


def normalise_work(work):
    work.artist_name, work.artist_honorifics = normalise_artist(work.raw_artist)
    work.price_numeric, work.price_text = parse_price(work.raw_price)
    work.edition_total, work.edition_price_numeric = parse_edition(work.raw_edition)

    if work.raw_title:
        work.title = str(work.raw_title).strip()

    if work.raw_medium:
        work.medium = str(work.raw_medium).strip()
