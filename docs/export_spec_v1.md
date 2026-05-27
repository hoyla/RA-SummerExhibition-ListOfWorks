# InDesign Tagged Text export specification

> **Related docs:** reading a corrected LOW export *back* into the tool is
> covered in [`reconcile.md`](./reconcile.md); services and data model are in
> [`architecture_v1.md`](./architecture_v1.md).

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

## File structure

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

## Component layout

The field order, separators, character styles, and **paragraph grouping** are all
configurable via `ExportConfig`. One template model serves two layouts (see
"Two layout models" below).

Default component order:

| Field       | Separator after | Default enabled |
| ----------- | --------------- | --------------- |
| work_number | tab             | yes             |
| artist      | tab             | yes             |
| title       | tab             | yes             |
| title_cased | tab             | no              |
| edition     | tab             | yes             |
| artwork     | tab             | no              |
| price       | none            | yes             |
| medium      | none            | yes             |

Components with `enabled=False` are omitted entirely from the output.
`title_cased` is the derived Title-Case form of the title (see
[`architecture_v1.md`](./architecture_v1.md)); it ships disabled in the LOW and
enabled in the LPG.

### Two layout models (LOW vs LPG)

Each component carries an optional `paragraph_style`. It is the single control
that picks the layout:

- **Blank → inline (the List of Works model).** The element stays in the current
  paragraph, wrapped in its character style and joined to the previous element by
  its separator. A whole LOW entry is therefore **one paragraph** (`entry_style`,
  e.g. `Title No Nest`) of character-styled, tab-separated runs.
- **Set → new paragraph (the Large Print Guide model).** The element **opens a new
  paragraph** in that paragraph style. An LPG work is therefore **several
  paragraphs** — number+title in `LPGTITLE`, then `LPGARTIST`, `LPGMEDIUM`,
  conditional `LPGEDITION`, `LPGPRICE` — typically with no character styles
  (the paragraph style does the work). Specifying a paragraph style *is* the
  line break.

The first component always opens the entry's first paragraph; its style is the
template's `entry_style`. A paragraph whose every component is empty and
omit-when-empty is dropped (e.g. the conditional `LPGEDITION`). The renderer
auto-selects the paragraphed path when any component declares a `paragraph_style`.

LPG example output:

```
<ParaStyle:LPGTITLE>1\tThe Meddling Fiend\r
<ParaStyle:LPGARTIST>Nicola Turner\r
<ParaStyle:LPGMEDIUM>mixed media\r
<ParaStyle:LPGEDITION>(edition of 10 at £500)\r
<ParaStyle:LPGPRICE>£5,000\r
```

### Per-room (per-section) export & filenames

The LPG is produced **one file per room**. A section-scoped export
(`GET /imports/{id}/sections/{section_id}/export-tags`) sets a download filename
embedding the template and gallery — e.g.
`Large-Print-Guide-2026_The-Annenberg-Courtyard.txt` — so individual gallery
files are distinguishable on disk. A blank `section_style` suppresses gallery
headings (the LPG has none).

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

## Separator types

| Key           | Output                                              |
| ------------- | --------------------------------------------------- |
| `none`        | nothing                                             |
| `space`       | space character                                     |
| `tab`         | real tab character (`\t`)                           |
| `right_tab`   | right-indent tab (uses InDesign tab stop)           |
| `soft_return` | soft return / forced line break (`\n`)              |
| `hard_return` | hard paragraph return (`\r<ParaStyle:entry_style>`) |

---

## Character styles

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
| title_cased | `WorkTitle`   |
| edition     | `Edition`     |
| price       | `Price`       |
| medium      | `Medium`      |
| artwork     | `Artwork`     |

In the editor, each element's character style is shown **on its own row** (next
to its separator and paragraph-style controls), but it is stored in these
per-field config slots — the data model is unchanged.

---

## Edition rules

| Condition       | Output                    |
| --------------- | ------------------------- |
| Total and price | `(edition of X at £Y)`    |
| Total only      | `(edition of X)`          |
| Total is 0      | suppressed (empty string) |
| Neither         | suppressed                |

The prefix `edition of` and bracketing are configurable via `ExportConfig`.
The rendered edition string is wrapped in the `edition` character style
(default `Edition`), so every field carries a character style.

Which editions are suppressed is an editorial choice, set by the normalisation
config's `edition_suppress_max` (default 0 = drop only "Edition of 0"; 1 also
drops "Edition of 1", which is the work itself). See the normalisation rules in
[`architecture_v1.md`](./architecture_v1.md).

---

## Price rules

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

## Override behaviour

When a `WorkOverride` exists for a work, its non-null values replace the
corresponding normalised `Work` values before export. A `None` override field
means "use the Work value". An empty string override outputs nothing for that field.

---

## InDesign dialects

Our renderer emits the **native** dialect (long `<ParaStyle:>` / `<CharStyle:>`
tags, CR paragraph breaks). A file **re-exported by InDesign** uses a different
dialect; the reconcile parser ([`reconcile.md`](./reconcile.md)) handles both.
A real InDesign re-export differs as follows:

- **Short tag forms** `<pstyle:Name>` / `<cstyle:Name>…<cstyle:>`.
- **LF paragraph breaks** (not CR), preceded by a preamble of `<vsn:>` / `<dps:>`
  / `<dcs:>` style definitions (discarded by the paragraph allowlist).
- **All non-ASCII escaped** as `<0x####>` even when Mac-Roman-encodable
  (`£` = `<0x00A3>`, `'` = `<0x2019>`) — so the file is plain ASCII.
- **A forced line break inside a paragraph is `<0x000A>`** — decoded then deleted
  like any soft return; the whole entry stays one paragraph.
- **Style names are backslash-escaped**: `<cstyle:Work Number\/Name>` — the parser
  unescapes them before matching against the template's style allowlist.
- **Inline local modifications** (e.g. `<ccase:…>`, a leading `<cl:…>`) can appear
  inside a styled run; the parser strips them.

These were confirmed against the real 2025 catalogue export, and are why
validating against a real file matters: a native-only parser returns zero entries
on any real InDesign re-export.

---

# Artists Index export specification

The Artists' Index is exported as InDesign Tagged Text with the same encoding
rules as the List of Works (ASCII-MAC, Mac Roman, CR line endings).

## File structure

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

## Entry format

Each artist entry is a single paragraph. The structure is:

```
<ParaStyle:entry_style>[RA-styled name] [qualifications]\t[cat numbers][\texpert numbers]
```

### RA member entries

For artists where `is_ra_member` is `True`:

1. **Surname** — rendered in `ra_surname_style` character style, uppercase
2. **Given name** — no special styling
3. **Qualifier** — rendered in `ra_caps_style` character style  
   (lowercased if `quals_lowercase=True`)

### Non-RA entries

- Name rendered without character styles
- Honorifics (if any) rendered in `honorifics_style`

### Additional artists

Index entries can have up to three artists. Additional artists (artist 2,
artist 3) are rendered after the primary artist's qualifications, each with
independent RA styling when `artistN_ra_styled` is set.

When there are **two** artists, artist 2 is prefixed with "and":

```
Sauerbruch, Matthias, and Peter St John, 42
```

When there are **three** artists, only the **last** gets "and" — the middle
artist is simply comma-separated (Oxford-comma style):

```
Eggerling, Gabriele, Dhruv Jadhav, and Hannah Puerta-Carlson, 100
```

## Character style boundaries

Character styles wrap **only the meaningful value**, never surrounding
separators (commas, spaces). For example:

```
<cstyle:RA Surname>Ackroyd<cstyle:>, Norman <cstyle:RA Caps>cbe ra<cstyle:>, <cstyle:CatNo>57<cstyle:>, <cstyle:CatNo>58<cstyle:>
```

Note: the comma-space after `Ackroyd`, after `cbe ra`, and between catalogue
numbers are all **outside** the `<cstyle:>` tags.

## Catalogue numbers

Cat numbers are joined with `cat_no_separator` (default `,`). Each number
is wrapped in `cat_no_style`. The separator itself can have an independent
`cat_no_separator_style`.

## Expert numbers

When `expert_numbers_enabled=True`, expert numbers are appended after a
right-aligned tab stop (`<cSpecialChar:Tab Align>`) and styled with
`expert_numbers_style`.

## Section separator

Between letter groups, a separator is inserted. The `section_separator`
field controls the type:

| Value          | Output                                            |
| -------------- | ------------------------------------------------- |
| `paragraph`    | Empty paragraph with `section_separator_style`    |
| `column_break` | `<cSpecialChar:Column Break>` in styled paragraph |
| `frame_break`  | `<cSpecialChar:Frame Break>` in styled paragraph  |
| `page_break`   | `<cSpecialChar:Page Break>` in styled paragraph   |
| `none`         | No separator                                      |

## IndexExportConfig fields

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

## Override behaviour

When an `IndexArtistOverride` exists, its non-null values replace the
corresponding `IndexArtist` values before export. Override fields set to
`None` mean "use the original value". Cat number overrides replace the
entire list of catalogue numbers.
