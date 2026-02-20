# InDesign Tagged Text Export Specification v1

## Encoding

- UTF-8
- text/plain
- Real control characters (not escaped)
- CR paragraph endings

---

## Structure

Each section:

<ParaStyle:SectionTitle>Section Name
<ParaStyle:CatalogueEntry>Number<TAB>Artist<TAB>Title<TAB>Price

Blank line between sections.

---

## Edition Rules

If edition_total and edition_price_numeric:
(edition of X at £Y)

If only edition_total:
(edition of X)

If edition_total is 0:
Suppress entirely.

---

## Price Rules

Numeric price → show numeric  
"NFS" → show NFS  
"_" or blank → show _

---

## Sanitisation

- Trim whitespace
- Preserve diacritics
- Preserve punctuation
- No escaped control characters
