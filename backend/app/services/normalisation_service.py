import re
from decimal import Decimal


def normalise_artist(raw_artist: str):
    if not raw_artist:
        return None, None

    artist = str(raw_artist).strip()
    return artist, None


def normalise_price(raw_price):
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
        return numeric, value
    except Exception:
        return None, value


def normalise_edition(raw_edition):
    if not raw_edition:
        return None, None

    value = str(raw_edition).strip()

    if value.startswith("Edition of 0"):
        return None, None

    full_match = re.match(r"Edition of (\d+) at .*?([0-9,]+\.?[0-9]*)", value)
    if full_match:
        total = int(full_match.group(1))
        price = Decimal(full_match.group(2).replace(",", ""))
        return total, price

    partial_match = re.match(r"Edition of (\d+)", value)
    if partial_match:
        total = int(partial_match.group(1))
        return total, None

    return None, None


def normalise_work(work):
    work.artist_name, work.artist_honorifics = normalise_artist(work.raw_artist)
    work.price_numeric, work.price_text = normalise_price(work.raw_price)
    work.edition_total, work.edition_price_numeric = normalise_edition(work.raw_edition)

    if work.raw_title:
        work.title = str(work.raw_title).strip()

    if work.raw_medium:
        work.medium = str(work.raw_medium).strip()
