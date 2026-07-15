# Extract EPUB Metadata
*Because sometimes AO3 goes down (gasp!), authors delete their works, or you end up with EPUBs of questionable provenance whose metadata never made it into Calibre. If the information is in the book, this plugin will try to rescue it.*

> **Disclaimer:** this was shamelessly vibe-coded. It's provided as-is, and support is minimal —
> issues and PRs are welcome, but don't expect a fast turnaround. Back up your library (or at
> least test on a couple of books first) before relying on it.

A Calibre plugin that extracts [FanFicFare](https://github.com/JimmXinu/FanFicFare)-compatible
metadata from an EPUB already in your library when FanFicFare can't (re)download the story—for
example because of Cloudflare, deleted works, manual downloads, or archived copies.

It reads the EPUB and recovers as much metadata as possible (title, author, fandom, relationships,
characters, tags, rating, warnings, word/chapter counts, dates, story URL, etc.), then does
whichever of the following you've enabled:

1. **Save all extracted metadata** (on by default) — stores the recovered metadata in a
   Saved Metadata column using FanFicFare's native format. You then run FFF's existing
   **"Update Calibre Metadata from Saved Metadata Column"** action to process it as if you were downloading it, using your
   existing `personal.ini` replacements, custom-column mappings, and cover generation. This mode
   deliberately does not re-implement any of FFF's metadata processing.

2. **Update standard Calibre metadata** (off by default) — writes directly to your library's
   Title, Author, Tags, Series and Comments using FanFicFare's default AO3 metadata mapping. No
   separate FFF update step is required. This is a simpler path intended for users who
   don't rely on extensive `personal.ini` customisation.

3. **Update custom columns** (off by default) — writes selected recovered metadata fields (such as
   fandom, word count or rating) directly to custom columns you choose.

The three options are independent and can be combined however you like. By default, only the
Saved Metadata option is enabled because it modifies only a single custom column. The
other two write more changes immediately to your metadata, so they're opt-in.

## What this plugin does *not* do

It doesn't download stories or replace FanFicFare — extraction only works with metadata already
present in the EPUB itself. And with only mode 1 enabled (the default), it never touches your
library's Title/Tags/Comments/etc. directly; it just reconstructs FanFicFare's Saved Metadata
column so FFF can do its thing. 

## How it works

Metadata is extracted from multiple sources, preferring the most complete source first:

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

- **Save all extracted metadata** (default on)
  - **Saved Metadata Column** — a Long Text ("comments") custom column. This should be the same
    column configured as FanFicFare's Saved Metadata column.
  - **Overwrite existing column value** — off by default; books with an existing value are skipped.
- **Update standard Calibre metadata** (default off)
  - **Overwrite existing values** — off by default; a field already populated in Calibre (e.g. an
    existing Title or Tags) is left alone rather than overwritten.
- **Update custom columns** (default off)
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
