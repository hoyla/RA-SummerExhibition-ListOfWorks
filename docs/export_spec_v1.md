# InDesign Tagged Text Export Specification

## Encoding

- File header: `<ASCII-MAC>`
- Byte encoding: Mac Roman (`mac_roman`)
- Characters outside Mac Roman: encoded as `<0x####>` (e.g. `<0x2019>` for `'`)
- Line endings: CR (`\r`) — one per paragraph
- MIME type: `text/plain`

---

## File Structure

```
<ASCII-MAC>\r
<ParaStyle:SectionTitle>Section Name\r
<ParaStyle:CatalogueEntry><CharStyle:CatNo>1<CharStyle:>\t<CharStyle:ArtistName>Artist Name RA<CharStyle:>\t...\r
\r
<ParaStyle:SectionTitle>Next Section\r
...
```

Sections are separated by a blank line (bare `\r`).

---

## Component Layout

Each catalogue entry is a single paragraph. The field order, separators,
and character styles are all configurable via `ExportConfig`.

Default component order:

| Field       | Separator after | Default enabled |
| ----------- | --------------- | --------------- |
| work_number | tab             | yes             |
| artist      | tab             | yes             |
| title       | tab             | yes             |
| edition     | tab             | yes             |
| artwork     | tab             | no              |
| price       | none            | yes             |
| medium      | none            | yes             |

Components with `enabled=False` are omitted entirely from the output.

When a component's value is empty and `omit_sep_when_empty=True` (default),
the separator after that component is also suppressed.

---

## Separator Types

| Key             | Output                                                      |
| --------------- | ----------------------------------------------------------- |
| `tab`           | real tab character (`\t`)                                   |
| `none`          | nothing                                                     |
| `new-paragraph` | `\r<ParaStyle:entry_style>` (continues same InDesign story) |

---

## Character Styles

Each field can have an associated character style name. If non-empty, the
value is wrapped: `<CharStyle:Name>value<CharStyle:>`. An empty style name
emits the value without tags.

Default style names:

| Field       | Default style |
| ----------- | ------------- |
| work_number | `CatNo`       |
| artist name | `ArtistName`  |
| honorifics  | `Honorifics`  |
| title       | `WorkTitle`   |
| price       | `Price`       |
| medium      | `Medium`      |
| artwork     | `Artwork`     |

---

## Edition Rules

| Condition       | Output                    |
| --------------- | ------------------------- |
| Total and price | `(edition of X at £Y)`    |
| Total only      | `(edition of X)`          |
| Total is 0      | suppressed (empty string) |
| Neither         | suppressed                |

The prefix `edition of` and bracketing are configurable via `ExportConfig`.

---

## Price Rules

| Condition     | Output                          |
| ------------- | ------------------------------- |
| Numeric value | `£1,200` (formatted per config) |
| `NFS`         | `NFS`                           |
| `_`           | `_`                             |
| blank / null  | suppressed                      |

Decimal places default to 0. Thousands separator defaults to `,`.

---

## Honorifics

Honorifics (e.g. `RA`, `Hon RA`) are split from the artist name during
normalisation and emitted with a separate character style immediately after
the artist name, separated by a space.

If `honorifics_lowercase=True`, honorifics are lowercased in the output.

---

## Override Behaviour

When a `WorkOverride` exists for a work, its non-null values replace the
corresponding normalised `Work` values before export. A `None` override field
means "use the Work value". An empty string override outputs nothing for that field.
