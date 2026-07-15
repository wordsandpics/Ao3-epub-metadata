# Extract EPUB Metadata

> **Disclaimer:** this was shamelessly vibe-coded. It's provided as-is, and support is minimal —
> issues and PRs are welcome, but don't expect a fast turnaround. Back up your library (or at
> least test on a couple of books first) before relying on it.

A Calibre plugin that extracts [FanFicFare](https://github.com/JimmXinu/FanFicFare)-compatible
metadata from an EPUB already in your library when FanFicFare can't (re)download the story—for
example because of Cloudflare, deleted works, manual/browser downloads, or archived copies.

It reads the EPUB and recovers as much metadata as possible (title, author, fandom, relationships,
characters, tags, rating, warnings, word/chapter counts, dates, story URL, etc.), then does
whichever of the following you've enabled:

1. **Write to Saved Metadata Column** (on by default) — stages the metadata in FanFicFare's own
   native format in a custom column. You then run FanFicFare's existing **"Update Calibre Metadata
   from Saved Metadata Column"** action as usual, preserving your existing `personal.ini`
   replacements, custom-column mappings, and cover generation. This mode deliberately does not
   re-implement any of FanFicFare's own metadata processing — FanFicFare remains the single source
   of truth for how that metadata becomes your library's actual Title/Tags/Comments/custom columns.
2. **Populate standard Calibre fields** (off by default) — writes directly into your library's
   Title/Author/Tags/Series/Comments, using FanFicFare's own default AO3 field-composition rules
   hardcoded rather than reimplemented as a general engine. No need to also run FanFicFare's own
   action. This is a simplified, no-round-trip path for the common case — it will never have
   FanFicFare's full `personal.ini` per-site customizability.
3. **Map metadata to custom columns** (off by default) — writes specific recovered fields (e.g.
   fandom, word count, rating) into custom columns you choose, independent of the two modes above.

The three are independent and combinable — enable any mix you want. Modes 2 and 3 modify your
library directly, not just a staging column, so they default off; mode 1 only stages a blob and
defaults on.

## What this plugin does *not* do

It doesn't download stories or replace FanFicFare — recovery only works with metadata already
present in the EPUB itself. And with only mode 1 enabled (the default), it never touches your
library's Title/Tags/Comments/etc. directly; it just reconstructs FanFicFare's Saved Metadata
column so FanFicFare can perform its normal metadata update. Modes 2/3 are opt-in exceptions to
that, by design.

## How it works

Metadata is recovered from multiple sources, in order of richness:

1. Standard EPUB/OPF metadata (title, authors, language, description, tags, `dc:source`).
2. A FanFicFare-generated title page, if the EPUB was originally produced by FanFicFare.
3. AO3's own native front-matter preface, if the EPUB was downloaded directly from
   [Archive of Our Own](https://archiveofourown.org).
4. A generic scan for the first recognized fanfic-site link, as a last-resort way to recover the
   story URL.

Earlier sources take precedence; later sources only fill in missing values.

When a story URL is recovered, the plugin can also add it as a `url` identifier (if one doesn't
already exist). FanFicFare uses this identifier to determine which site adapter to use when it
later imports the Saved Metadata — relevant to mode 1's round trip, but harmless to leave on
regardless of which modes you use.

## Installing

```sh
# from this directory
/Applications/calibre.app/Contents/MacOS/calibre-customize -b extract_epub_metadata
```

(On Linux/Windows, use whichever `calibre-customize` is on your `PATH`.) Or, in the Calibre GUI:
Preferences → Plugins → Load plugin from file, pointing at a zipped copy of the
`extract_epub_metadata/` directory.

## Configuring

In Preferences → Plugins → Extract EPUB Metadata → Customize plugin, each mode is its own
checkable section:

- **Write to Saved Metadata Column** (default on)
  - **Saved Metadata Column** — a Long Text ("comments") custom column. This should be the same
    column configured as FanFicFare's Saved Metadata column.
  - **Overwrite existing column value** — off by default; books with an existing value are skipped.
- **Populate standard Calibre fields** (default off)
  - **Overwrite existing values** — off by default; a field already populated in Calibre (e.g. an
    existing Title or Tags) is left alone rather than overwritten.
- **Map metadata to custom columns** (default off)
  - **Configure column mapping…** opens a dialog listing your custom columns (of a supported
    datatype: text, comments, enumeration, series, bool, int, float, datetime), each with a
    dropdown of recovered-metadata fields compatible with that column's type. Leave a column
    "(not mapped)" to never touch it.

Independent of all three modes:

- **Add missing story-URL identifier** — on by default; only adds a `url` identifier when the
  book doesn't already have one.
- **Preview before writing** — on by default; review everything that would be written, across
  whichever modes are enabled, before anything is written.

## Usage

Select one or more books with an EPUB, click the **Extract Metadata** toolbar button, review the
preview, and confirm. If you're using mode 1 (Saved Metadata Column), follow up by running
FanFicFare's **Update Calibre Metadata from Saved Metadata Column** action. If you're only using
modes 2/3, your library fields are already updated — no further action needed.

## Development

```sh
python3 -m unittest discover -s tests -v
```

The test suite is stdlib-only (`unittest`, `xml.etree.ElementTree`) and runs without Calibre
installed, using a minimal stub in `tests/calibre_stub/` so
`extract_epub_metadata/__init__.py` can be imported outside a real Calibre environment. It
runs against real fixtures in `tests/fixtures/`, including an actual AO3-downloaded EPUB and a
real Saved Metadata column value.

One test (`test_round_trips_through_fanficfare_load_html_metadata`) additionally verifies against
FanFicFare's own installed `load_html_metadata()` when available, and skips cleanly otherwise.
