# LOW → LPG reconciliation — feature roadmap

> **⚠️ Temporary working document.** This tracks an in-progress feature so it can
> be handed between sessions and people. It is intended to evolve as we build,
> and to be **deleted when the feature is complete**. Branch: `low-tag-reimport-diff`.
>
> **Status:** in progress. Done: edition character style (#1); parser
> `low_tag_parser.py` (#2); round-trip identity gate (#3, **passing** incl. the
> 2026 wrap + style-collision + price-interleave case); matching + 2-way diff +
> significance tiering `low_diff.py` (#4, #5); canonical-mutation tests (#7);
> thin ingestion endpoint `POST /imports/{id}/low-tag-diff` (#6). The detection
> engine works end to end through HTTP (838 tests), and is **dialect-tolerant**
> (handles both our tags and the real InDesign short dialect — see §6).
> **Next / blocked on a real file:** validate against a real corrected LOW
> export, then build the report UI + snapshot persistence (#8).
> **Last updated:** 2026-05-26.

---

## 1. The problem

The tool treats the **database** (normalised + corrected spreadsheet data) as the
single source of truth, from which we produce two parallel outputs:

- **LOW** — List of Works, the printed catalogue, exported as InDesign Tagged Text.
- **LPG** — Large Print Guide: large-text A4 printouts of the same content for
  readers who can't read the small catalogue type. **One printout per room.**

The single-source-of-truth breaks down downstream. After the LOW tags are placed
in InDesign, a staffer applies **last-minute data corrections** directly in the
InDesign LOW file (artist text changes, title tweaks, etc.). Those corrections
never flow back to the database, so if the LPG is generated from the database it
**misses them**.

### Why we can't just fix it upstream

The obvious fix — enter all corrections in the tool, re-export, re-place — is
**impractical**, and the reason is *hard*, not habit:

- Downstream work on the LOW is **design-led** (layout, pagination, inline
  pictures, content types that never existed in our data). Re-importing tags at
  the last minute would destroy that design work, which can't be redone in time.

So corrections legitimately happen in InDesign, and we need a way to get the
**data changes** back out.

## 2. The mission

Treat the database as the source of truth, but **diff it against the final
corrected LOW** to identify data corrections that were made downstream, so they
can be reflected in the LPG before it's printed.

**The LPG is held until the last minute** (it's just printouts, not a bound
product), which makes this workflow viable.

### Workflow

1. Export LOW tags, produce the LOW as normal.
2. Downstream, the staffer makes last-minute corrections in the InDesign LOW.
3. Export tags from the corrected LOW.
4. Import those tags back into the tool (new parser).
5. **Diff** the corrected LOW against the database; surface the significant
   differences.
6. A human routes each difference to the right fix (see §4, "fix channels").
7. Once corrections are in the database, export the LPG.

## 3. Scope

### In scope (MVP)

- A parser that reads corrected LOW Tagged Text back into structured field values.
- A **2-way diff** between the parsed LOW and the current database.
- A **disparity report**: significant differences, ranked by severity, tagged
  with the natural fix channel. **Detection only.**
- List of Works only.

### Explicitly out of scope (MVP)

- **Disparity *resolution*.** No auto-merge, no accept-to-override UI. The MVP
  *identifies* differences; humans fix them via existing channels.
- **Artists' Index.** Same shape later, but the Index has no re-import path yet.
- **3-way merge / base snapshot.** Not needed — see decision D7.

## 4. Key decisions (with rationale)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Detection, not resolution, for the MVP.** | Goal is to identify *significant* differences, not fix everything. Avoids the editorially-fraught auto-merge; keeps a human in the loop. |
| D2 | **Database stays the source of truth; LPG is a parallel output.** | The whole point. We pull downstream corrections *back* into the DB, then the LPG (and any re-export) flows from it. |
| D3 | **Parse by character-style spans, not by position.** | Generation is lossy and configurable; positional inversion is fragile against hand-edits, wrapping and interleaving. Character-style tags (`<CharStyle:…>`) are self-labelling field delimiters and survive all of it. See §6 evidence. |
| D4 | **Every data field must carry a character style** (incl. edition). | Span-based parsing — and lossless wrap inversion — only work if each field is styled. Edition is currently emitted *unstyled* (§6). Luke is adding an edition character style to the InDesign template; we mirror it in our renderer + seed templates (task #1). Assume henceforth edition is always styled. |
| D5 | **Parser output is layout-free.** A flat `{cat_no, section, title, artist, honorifics, price, edition, artwork, medium}` record per entry. | We only need to *distinguish* fields and detect changes — not reconstruct where anything sat. The LPG re-lays-out from field values (e.g. price on its own line), so LOW layout is irrelevant. |
| D6 | **Match: cat-number two-pass join; rooms aligned by membership overlap.** | Cat number is the join key but **can change (only via mistakes)**, so: exact cat-no match first, then surface orphans. Align rooms by maximal cat-number overlap, **not** by section-title text (designers embellish headings for print). |
| D7 | **2-way diff only** (parsed LOW vs current DB). | Luke makes the post-export upstream edits himself and can record them, so "we changed it since export" findings are self-known. No base snapshot needed. |
| D8 | **Significance tiering is a data-driven config, not hardcoded.** | Reuse the `Ruleset`/JSONB pattern (as templates + normalisation config already do) so tiers can be tuned live. Default: structural = high, text-field = medium, cosmetic = suppressed. |
| D9 | **Suppress cosmetic noise.** Normalise *both* sides before comparing: collapse whitespace/soft returns, NFC-normalise, de-format price/edition. | "Significant" means signal over noise. Catches phantom diffs from wrapping, smart-vs-straight quotes, Mac-Roman escapes, honorific casing, and human re-typing artefacts. |
| D10 | **Categorise each finding by its natural fix channel.** | text-field change → an override (resolution is post-MVP); room move / renumber / add / remove → fix the master spreadsheet and re-import via the existing reimport+diff path. The report routes; it doesn't guess. |
| D11 | **Provenance: store imported corrected tags as an immutable, timestamped snapshot.** | Append-only, defensible: which corrections were detected, from which file, when. Consistent with the repo's "never mutate raw / append-only / provenance" principles. |

## 5. Parser rules (`low_tag_parser.py`)

Concrete algorithm, all grounded in the real renderer (§6):

1. **Template-driven.** The `ExportConfig` that produced the file supplies the
   style-name *allowlist* and the price/edition format inverters. → the import
   flow must know **which export template produced the file**.
2. **Allowlist, not denylist.** Two stages:
   - *Paragraph pass*: keep only paragraphs whose `<ParaStyle:…>` is the entry
     style or the section style. Everything else (design furniture, inline
     pictures, foreign content types) is never considered.
   - *Character-span pass*: within kept paragraphs, read only the known
     `<CharStyle:…>` spans.
   - Belt-and-braces: keep an entry paragraph only if it also yields a cat number.
3. **Section tracking.** Walk the stream; each `<ParaStyle:SectionTitle>`
   paragraph updates "current room"; each entry inherits it.
4. **Entry delimitation.** An entry runs from one CatNo span to the next CatNo
   span (or a section title). Robust to entries split across `\r` by hard-return
   separators.
5. **Field assembly.** Collect every fragment by character style **in document
   order**, concatenate **without inserting separators**, then **delete soft
   returns** (`\n`). This reconstructs each field's pre-wrap value exactly, even
   when a field is split into multiple same-style spans (e.g. the title around an
   interleaved price).
6. **Encoding.** Decode `<0x####>` escapes and Mac-Roman bytes; NFC-normalise.
7. **Format inversion.** Price: strip currency symbol + thousands separators →
   numeric. Edition: invert `(edition of X at £Y)` → total + price.
8. **Defensive count check.** After parsing, reconcile parsed-entry count against
   the works that were in the official export; **warn loudly on a shortfall**
   (catches an allowlist that's too strict because a designer restyled entries).
   Never silently succeed on a partial parse.

## 6. Renderer evidence (so future sessions don't re-derive it)

From `backend/app/services/export_renderer.py`:

- **Edition is the only core field emitted with no character style** — there is no
  `edition_style` in `ExportConfig`; `edition_display` is inserted bare
  (`render_import_as_tagged_text`, ~line 486). This is the one field that forces
  positional parsing today, and the reason for decision D4.
- **The renderer only ever *splits* text — it never injects characters.**
  `_wrap_lines` breaks at a space and keeps the breaking space trailing on the
  current line; lines are joined with `\n`. Therefore **deleting `\n` is an exact
  inverse** of wrapping — for both space-breaks and mid-word hard-breaks.
  `_balance_wrap_lines` just re-runs `_wrap_lines` at a narrower width (same
  property).
- **Price repositioning (`end_of_first_line`)** emits the title as **two separate
  `<CharStyle:WorkTitle>` spans** with the `<CharStyle:Price>` span between them.
  Collecting same-style fragments in document order recovers the full title; the
  price is read independently. Layout position is discarded (D5).
- **Hard-return separators** re-emit `<ParaStyle:entry_style>`, so one logical
  entry can span multiple `\r` paragraphs — hence the "CatNo-span to next
  CatNo-span" entry rule (§5.4).
- Honorifics are appended to the artist as ` ` + a separate
  `<CharStyle:Honorifics>` span → recovered as a distinct field.
- **Style collision (found while building):** the production 2026 template styles
  **both** the work number and the title as `Work Number/Name`. Group-by-style
  alone would merge them, so collisions are resolved by component order — the
  first span of a shared style is the earlier component (work number), the rest
  the later (title). Verified by round-trip test.
- **One entry == one entry-style paragraph** for the current templates: both use
  soft returns (and tabs/column breaks) within an entry, never hard returns. So
  entries are delimited by entry-style paragraphs. Hard-return continuation
  merging is deferred (the defensive count check in §5.8 would flag it).
- **Comparison is at the display-string level** (decision refined): because the
  MVP only detects (doesn't resolve), the parser recovers each field's display
  string and the diff compares strings — so we never invert `£1,200` → `1200`
  or `(edition of 5 at £200)` back into numbers. `low_diff.work_display_fields`
  computes the DB side the same way for like-for-like comparison.
- **Real InDesign dialect differs from our renderer** (found in the
  `test_sample_files/` real export). InDesign re-exports use the **short** tag
  forms `<pstyle:Name>` / `<cstyle:Name>…<cstyle:>` (not `<ParaStyle:>` /
  `<CharStyle:>`), **LF paragraph breaks** (not CR), and a preamble of `<vsn:>`
  / `<dps:>` / `<dcs:>` style definitions. The parser now handles both dialects
  (tag-name + line-ending), and the paragraph allowlist discards the preamble.
  This is exactly why validating against a real file matters — a native-only
  parser would have returned zero entries on any real re-export.

## 7. Architecture / where things live

- **New:** `backend/app/services/low_tag_parser.py` — the parser (§5).
- **New/extended:** a comparison service (sibling to, or extension of,
  `backend/app/services/export_diff_service.py`, which already flattens by
  catalogue number and compares fields). Adds room alignment + cat-no orphan
  handling + significance tiering.
- **New:** immutable snapshot storage for imported corrected tags (provenance, D11).
- **Renderer/config:** add `edition_style` to `ExportConfig` + wrap edition in
  `_cs()`; update default config and `backend/seed_templates/*.json` (task #1).
- **Significance config:** a `Ruleset`-style JSON config (D8).
- **Frontend:** a read-only disparity report view, reusing existing diff-panel
  patterns; grouped/filterable by severity and fix channel.
- **Tests:** pytest, SQLite in-memory, no Docker (the renderer runs on the test
  session). Sample inputs in `test_sample_files/`.

## 8. Build sequence

Tracked as session tasks #1–#7. The **feasibility gate is round-trip identity**
(#3): if an *unmodified* exported file doesn't parse straight back to the
resolved DB values, every diff is false positives.

1. ✅ Add `edition_style` to renderer, default config + seed templates. *(prereq for clean round-trip)*
2. ✅ Build `low_tag_parser.py` (character-style span parser).
3. ✅ **Round-trip identity harness + test** — export → parse → assert equality on an unmodified file. *(gate — passing)*
4. ✅ Matching service — cat-no two-pass join + room alignment by membership overlap.
5. ✅ 2-way field diff + data-driven significance tiering + cosmetic suppression.
6. ✅ Thin ingestion endpoint `POST /imports/{id}/low-tag-diff` (parse + diff → JSON, dialect-tolerant, no persistence/UI).
8. Report UI + snapshot persistence — **deferred** until validated against a real corrected LOW file.
7. ✅ Canonical test mutations — text edit, room move, renumber — assert correct classification.

## 9. Open questions / pending

- **Real corrected-tags sample.** The thin endpoint (`POST /imports/{id}/
  low-tag-diff`) is ready to point at a real corrected LOW export. The one
  dialect detail still unconfirmed: how InDesign's short dialect represents a
  **forced line break within a paragraph** (the wrap/soft-return case) — the
  sample available was an Index export without LOW-style wrapping. A real
  wrapped LOW re-export will settle it; the parser's soft-return handling may
  need a small tweak then. The diagnostic short-parse warning in the endpoint
  will flag if a real file doesn't parse as expected.
- ~~**Edition character style.**~~ ✅ Confirmed: the InDesign test template uses
  `Work Edition`, which is exactly what the 2026 seed template now specifies and
  what the round-trip test exercises.
- **Template pinning.** Import flow needs to know which export template produced
  the file (drives the allowlist + format inverters).
- **Does a moved room count as a data change?** Yes — confirmed first-class for
  the LPG (one printout per room; a mover prints in the wrong booklet). High severity.
- **Report export?** Whether the disparity report needs an xlsx/JSON export to
  hand to whoever edits the master spreadsheet. Possible nice-to-have.
- **Renumber auto-correlation.** Content-matching orphans (artist+title) to
  auto-label probable renumberings — fast-follow, not MVP.

## 10. Glossary

- **LOW** — List of Works (the printed catalogue).
- **LPG** — Large Print Guide (large-text A4 printouts, one per room).
- **Tagged Text** — InDesign's import/export text format (`<ASCII-MAC>`,
  Mac-Roman bytes, CR line endings, `<ParaStyle:…>` / `<CharStyle:…>` tags).
- **Override** — editorial correction layer; never mutates raw/normalised data.
</content>
</invoke>
