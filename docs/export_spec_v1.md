# InDesign Tagged Text Export Specification

## Encoding

- File header: `<ASCII-MAC>`
- Byte encoding: Mac Roman (`mac_roman`)
- Characters outside Mac Roman: encoded as `<0x####>` (e.g. `<0x2019>` for `'`)
- Line endings: CR (`\r`) — one per paragraph
- MIME type: `text/plain`

**Why ASCII-MAC?** InDesign's Tagged Text importer on macOS requires the file to
declare its encoding via the header token. `<ASCII-MAC>` with Mac Roman bytes is
the only combination reliably recognised. UTF-8 (`<UNICODE-UTF8>`) and Windows
codepage 1252 (`<ASCII-WIN>`) were both tested and rejected by InDesign without
error. Characters that don't exist in Mac Roman are passed through as InDesign's
`<0x####>` numeric escape, which InDesign resolves correctly on import.

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

### Line wrapping

`max_line_chars` (integer or `null`) sets a soft wrap width for a component.
When set, the value is broken across multiple soft-return-separated lines.

`balance_lines` (boolean) redistributes the wrapped lines so they are as
equal in length as possible, rather than filling each line to the limit.

`next_component_position` controls where the _next_ component is placed
relative to a wrapped field:

| Value               | Meaning                                         |
| ------------------- | ----------------------------------------------- |
| `end_of_text`       | next component starts after all wrapped lines   |
| `end_of_first_line` | next component continues on the same first line |

---

## Separator Types

| Key           | Output                                              |
| ------------- | --------------------------------------------------- |
| `none`        | nothing                                             |
| `space`       | space character                                     |
| `tab`         | real tab character (`\t`)                           |
| `right_tab`   | right-indent tab (uses InDesign tab stop)           |
| `soft_return` | soft return / forced line break (`\n`)              |
| `hard_return` | hard paragraph return (`\r<ParaStyle:entry_style>`) |

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

---

---

# Artists' Index Export Specification

The Artists' Index is exported as InDesign Tagged Text with the same encoding
rules as the List of Works (ASCII-MAC, Mac Roman, CR line endings).

## File Structure

```
<ASCII-MAC>\r
<ParaStyle:SepStyle>\r
<ParaStyle:EntryStyle><CharStyle:RASurname>ABBOT<CharStyle:>, Liz <CharStyle:RACaps>ra<CharStyle:>\t<CharStyle:CatNo>23<CharStyle:><cSpecialChar:Tab Align><CharStyle:Expert>e23<CharStyle:>\r
<ParaStyle:EntryStyle>ADAMS, John\t<CharStyle:CatNo>45, 67<CharStyle:>\r
<ParaStyle:SepStyle>\r
<ParaStyle:EntryStyle><CharStyle:RASurname>BAKER<CharStyle:>, Tom <CharStyle:RACaps>hon ra<CharStyle:>\t<CharStyle:CatNo>12<CharStyle:>\r
...
```

Entries are grouped alphabetically by the first letter of `sort_key`. A
configurable section separator is inserted between letter groups.

## Entry Format

Each artist entry is a single paragraph. The structure is:

```
<ParaStyle:entry_style>[RA-styled name] [qualifications]\t[cat numbers][\texpert numbers]
```

### RA Member Entries

For artists where `is_ra_member` is `True`:

1. **Surname** — rendered in `ra_surname_style` character style, uppercase
2. **Given name** — no special styling
3. **Qualifier** — rendered in `ra_caps_style` character style  
   (lowercased if `quals_lowercase=True`)

### Non-RA Entries

- Name rendered without character styles
- Honorifics (if any) rendered in `honorifics_style`

### Second Artist

Linked entries (`&`) and multi-name entries render a second artist name
after the primary. The second artist gets independent RA styling when
`second_artist_is_ra` is set.

## Catalogue Numbers

Cat numbers are joined with `cat_no_separator` (default `,`). Each number
is wrapped in `cat_no_style`. The separator itself can have an independent
`cat_no_separator_style`.

## Expert Numbers

When `expert_numbers_enabled=True`, expert numbers are appended after a
right-aligned tab stop (`<cSpecialChar:Tab Align>`) and styled with
`expert_numbers_style`.

## Section Separator

Between letter groups, a separator is inserted. The `section_separator`
field controls the type:

| Value          | Output                                            |
| -------------- | ------------------------------------------------- |
| `paragraph`    | Empty paragraph with `section_separator_style`    |
| `column_break` | `<cSpecialChar:Column Break>` in styled paragraph |
| `frame_break`  | `<cSpecialChar:Frame Break>` in styled paragraph  |
| `page_break`   | `<cSpecialChar:Page Break>` in styled paragraph   |
| `none`         | No separator                                      |

## IndexExportConfig Fields

| Field                     | Type    | Default       | Description                           |
| ------------------------- | ------- | ------------- | ------------------------------------- |
| `entry_style`             | string  | `""`          | Paragraph style for each entry        |
| `ra_surname_style`        | string  | `""`          | Character style for RA surnames       |
| `ra_caps_style`           | string  | `""`          | Character style for RA qualifications |
| `cat_no_style`            | string  | `""`          | Character style for catalogue numbers |
| `honorifics_style`        | string  | `""`          | Character style for non-RA honorifics |
| `expert_numbers_style`    | string  | `""`          | Character style for expert numbers    |
| `quals_lowercase`         | boolean | `false`       | Lowercase RA qualifications           |
| `expert_numbers_enabled`  | boolean | `false`       | Include expert numbers in output      |
| `cat_no_separator`        | string  | `", "`        | Separator between catalogue numbers   |
| `cat_no_separator_style`  | string  | `""`          | Character style for the separator     |
| `section_separator`       | string  | `"paragraph"` | Separator type between letter groups  |
| `section_separator_style` | string  | `""`          | Paragraph style for the separator     |

## Override Behaviour

When an `IndexArtistOverride` exists, its non-null values replace the
corresponding `IndexArtist` values before export. Override fields set to
`None` mean "use the original value". Cat number overrides replace the
entire list of catalogue numbers.
