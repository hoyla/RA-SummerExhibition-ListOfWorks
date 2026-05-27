# LOW → LPG reconciliation

How the tool pulls last-minute data corrections — made downstream in the
printed **List of Works** (LOW) — back out of the corrected InDesign file and
into the database, so the **Large Print Guide** (LPG) reflects them.

**Related docs:** the InDesign Tagged Text format and the export/template model
this feature reads are documented in [`export_spec_v1.md`](./export_spec_v1.md);
the services, endpoints, and data model are in
[`architecture_v1.md`](./architecture_v1.md).

---

## 1. Why this exists

The database (normalised spreadsheet data + the editorial override layer) is the
single source of truth, and two parallel outputs flow from it:

- **LOW** — the printed catalogue, exported as InDesign Tagged Text.
- **LPG** — large-text A4 printouts of the same content, **one per room**.

The single source of truth breaks down downstream: once the LOW tags are placed
in InDesign, staff apply **last-minute data corrections directly in the InDesign
file** (artist/title tweaks, etc.). That downstream work is *design-led*
(pagination, inline pictures, content types that never existed in our data), so
re-importing tags at the last minute would destroy it. The corrections therefore
legitimately live only in the InDesign LOW — and if the LPG is generated from the
database, it misses them.

Because the LPG is held until the last minute (it's just printouts, not a bound
product), there's a window to **diff the corrected LOW against the database**,
surface the data corrections, fold them in, then print the LPG.

## 2. Workflow

1. Export LOW tags; produce the printed LOW as normal.
2. Downstream, staff make last-minute corrections in the InDesign LOW.
3. Export tags from the *corrected* LOW.
4. Upload them in the tool's **Reconcile** panel (choosing the template that
   produced the file).
5. The tool diffs the corrected LOW against the current database and surfaces the
   significant differences, each tagged with how to fix it.
6. A human routes each difference: text changes → a per-work **override**;
   structural changes (room move, renumber, add/remove) → fix the master
   spreadsheet and re-import.
7. Re-check against current data (the diff recomputes live); once clean, export
   the LPG.

**Detection only.** The MVP identifies differences; it never auto-merges. A human
resolves each one through the existing channels.

## 3. Design decisions

| # | Decision | Why |
|---|----------|-----|
| D1 | Detection, not resolution | Identify *significant* differences; keep a human in the loop, avoid editorially-fraught auto-merge. |
| D2 | DB stays source of truth; LPG is a parallel output | Corrections are pulled *back* into the DB, then outputs flow from it. |
| D3 | **Parse by character-style spans, not position** | Generation is lossy/configurable; positional parsing is fragile against hand-edits, wrapping, interleaving. `<CharStyle:…>` tags are self-labelling and survive all of it. |
| D4 | Every reconciled field carries a character style | Span-based parsing only works if each field is styled. (This is why `edition_style` was added.) |
| D5 | Parser output is layout-free | A flat record per entry; we only need to *distinguish* fields and detect changes, not reconstruct layout. The LPG re-lays-out from field values. |
| D6 | Match by catalogue number; align rooms by membership overlap | Cat number is the join key (can change only by mistake); rooms aligned by shared cat numbers, **not** heading text (designers embellish headings). |
| D7 | 2-way diff (parsed LOW vs current DB) | The post-export upstream edits are made by the editor and are self-known; no base snapshot needed. |
| D8 | Significance tiering is data-driven config | A `Ruleset` JSON (like templates / normalisation). Default: structural = high, text = medium, cosmetic = suppressed. Surfaced read-only at `GET /reconcile-config`. |
| D9 | Suppress cosmetic noise | Normalise both sides before comparing (collapse whitespace/soft returns, NFC, fold smart/straight quotes, de-format price/edition) so wrapping and re-typing artefacts don't read as changes. |
| D10 | Categorise each finding by fix channel | text change → override; room move / renumber / add / remove → spreadsheet re-import. The report routes; it doesn't guess. |
| D11 | Store imported corrected tags as an immutable, timestamped snapshot | Append-only provenance: which corrections were detected, from which file, when. |

## 4. The parser (`low_tag_parser.py`)

`parse_low_tags(text, config)` reads a corrected LOW Tagged Text file into a flat
list of `ParsedEntry` records. It is **template-driven** — the `ExportConfig`
that produced the file supplies the style-name allowlist — and works in two
passes:

1. **Paragraph pass.** Keep only paragraphs whose paragraph style is the
   template's `entry_style` or a section-heading style (`section_style` +
   `section_styles`). Everything else (design furniture, inline pictures, the
   `<vsn:>`/`<dps:>`/`<dcs:>` preamble) is never considered.
2. **Character-span pass.** Within a kept entry paragraph, read the known
   `<CharStyle:…>` spans and map each style name → field via the template's
   per-field style slots (`cat_no_style`, `artist_style`, …). Fragments of the
   same style are concatenated in document order and soft returns deleted, which
   exactly inverts the renderer's line wrapping.

A few robustness rules:

- **Style collisions.** When two fields share one character style (the LOW styles
  both the catalogue number and title as `Work Number/Name`), the merged run is
  split on the tab and assigned **by component order** — first piece = number,
  rest = title. Local modifications (inline tags, control chars, stray
  whitespace) inside the run are cleaned and dropped.
- **Dialect tolerance.** Real InDesign re-exports use a different dialect from our
  renderer (short `<pstyle>`/`<cstyle>` tags, LF breaks, `<0x####>` escapes). The
  parser handles both — see [`export_spec_v1.md`](./export_spec_v1.md#indesign-dialects).
- **Defensive count check.** If far fewer entries parse than the import holds, the
  endpoint warns loudly rather than silently returning a partial (mis-styled)
  diff.

The **feasibility gate** is *round-trip identity*: an unmodified export must parse
straight back to the values it was rendered from. If it doesn't, every later diff
is a false positive. This is locked in by `tests/test_low_tag_parser.py` and
`tests/test_low_real_sample.py` (the real 2025 export, 1729/1729, 0 findings).

## 5. The diff (`low_diff.py`)

`diff_low(parsed, collected, config, diff_config)` compares the parsed LOW against
the import's current resolved data (override-aware) and returns classified
`findings`, the room `section_alignment`, `counts`, and a separate `cosmetic`
list (differences that vanish after normalisation — suppressed, never surfaced as
findings). `LowDiffConfig` holds the severity tiers, fix-channel routing, and the
cosmetic/typographic-folding switches; `GET /reconcile-config` exposes it
read-only for the Settings page so the surfaced rules can't drift from behaviour.

## 6. Snapshots & provenance

Uploaded corrected files are stored append-only in the `low_tag_snapshots` table
(one inline copy per upload, timestamped). The diff is **recomputed live** on
every view against the *current* database — so as the editor applies overrides or
re-imports a corrected spreadsheet, re-viewing a stored snapshot shows the
resolved disparities drop off (the "Workflow A" loop). Endpoints live in
`backend/app/api/low_reconcile.py`.

## 7. Fragility boundary — what's safe to change in a future LOW template

The reconciler keys off **character styles** and assumes **one work = one
paragraph**. That makes it robust to a wide range of template changes and fragile
to exactly one structural change. Know the boundary before redesigning the LOW.

**Safe** (the parser shrugs these off — each field is found by its own style, and
the diff treats separator/whitespace differences as cosmetic):

- Different **separators** between elements (tab ↔ space ↔ soft return).
- **Reordered** elements.
- **Renamed / added / removed** character styles (a field with no style simply
  becomes unrecoverable — the diff skips it, no crash).
- Different section-heading styles.

**One within-paragraph caveat — shared character styles (a "collision").** Where
two fields share one style (e.g. cat-no + title on `Work Number/Name`), the
parser falls back to splitting on the **tab** and assigning **by order**. There,
changing the separator between them away from a tab, or swapping their order,
will misparse those two fields. Distinctly-styled fields have neither problem.

**Breaks — multiple paragraphs per entry.** The parser only parses paragraphs
whose style is `entry_style`, and bundles all of an entry's fields from that one
paragraph. Split a LOW entry across several paragraphs (each in its own paragraph
style) and only the first is parsed; the rest are skipped and their fields lost.
This is the same reason the **LPG can't be reconciled** today — an LPG work spans
five paragraphs (`LPGTITLE`, `LPGARTIST`, `LPGMEDIUM`, `LPGEDITION`, `LPGPRICE`),
and the parser never opens the non-`entry_style` ones. (The LPG is a generated
output, never re-imported, so this is by design — but it's the canonical example
of a "multi-paragraph LOW".)

It fails **loudly and safely**, not silently: the endpoint emits a "no/few
entries parsed" warning, so a broken reconcile looks obviously broken (everything
unparsed) rather than producing subtly-wrong diffs.

### Pre-flight check for any new template

Before trusting a redesigned LOW template for reconciliation, **export an import
with it and reconcile that file straight back**. Full parse count and ~0 findings
on an *unmodified* export = reconcile-safe. Anything else points at the fragile
spot (almost always a shared-style collision, or a move to multi-paragraph
entries).

### If you ever do go multi-paragraph

It's a bounded parser enhancement, to be done **in the same change** as the LOW
redesign: allowlist the element paragraph styles, map fields by **paragraph**
style (the template already stores `paragraph_style` per element — see the
template model in [`export_spec_v1.md`](./export_spec_v1.md)), and stitch
consecutive element-paragraphs into one entry (a new entry begins at each
catalogue-number paragraph). That same work would also make the LPG reconcilable,
were that ever wanted.

## 8. Glossary

- **LOW** — List of Works (the printed catalogue).
- **LPG** — Large Print Guide (large-text A4 printouts, one per room).
- **Tagged Text** — InDesign's import/export text format. See
  [`export_spec_v1.md`](./export_spec_v1.md).
- **Override** — the editorial correction layer; never mutates raw/normalised data.
- **Fix channel** — the route a finding takes to resolution: per-work *override*
  (text) or *spreadsheet re-import* (structural).
