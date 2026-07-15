# Extract EPUB Metadata

> **Disclaimer:** this was shamelessly vibe-coded. It's provided as-is, and support is minimal —
> issues and PRs are welcome, but don't expect a fast turnaround. Back up your library (or at
> least test on a couple of books first) before relying on it.

A Calibre plugin that extracts [FanFicFare](https://github.com/JimmXinu/FanFicFare)-compatible
metadata from an EPUB already in your library when FanFicFare can't (re)download the story—for
example because of Cloudflare, deleted works, manual/browser downloads, or archived copies.

It reads the EPUB, recovers as much metadata as possible (title, author, fandom, relationships,
characters, tags, rating, warnings, word/chapter counts, dates, story URL, etc.), and writes it
to a configured "Saved Metadata" custom column using FanFicFare's native format. You can then run
FanFicFare's existing **"Update Calibre Metadata from Saved Metadata Column"** action as usual,
preserving your existing `personal.ini` replacements, custom-column mappings, and cover generation.

This plugin deliberately does not re-implement any of FanFicFare's own metadata processing. It
simply extracts metadata, maps field names, and writes the Saved Metadata column. FanFicFare
remains the single source of truth for how that metadata becomes your library's actual
Title/Tags/Comments/custom columns.

## What this plugin does *not* do

This plugin does not update your Calibre metadata directly, download stories, or replace
FanFicFare. It simply reconstructs FanFicFare's Saved Metadata column from an existing EPUB so
that FanFicFare can perform its normal metadata update.

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
later imports the Saved Metadata.

Aside from the optional `url` identifier, the plugin never modifies your library metadata
directly. It only writes to the configured Saved Metadata column.

## Installing

```sh
# from this directory
/Applications/calibre.app/Contents/MacOS/calibre-customize -b extract_epub_metadata
```

(On Linux/Windows, use whichever `calibre-customize` is on your `PATH`.) Or, in the Calibre GUI:
Preferences → Plugins → Load plugin from file, pointing at a zipped copy of the
`extract_epub_metadata/` directory.

## Configuring

In Preferences → Plugins → Extract EPUB Metadata → Customize plugin:

- **Saved Metadata Column** — a Long Text ("comments") custom column. This should be the same
  column configured as FanFicFare's Saved Metadata column.
- **Overwrite existing column value** — off by default; books with an existing value are skipped.
- **Preview before writing** — on by default; review recovered fields before anything is written.
- **Add missing story-URL identifier** — on by default; only adds a `url` identifier when the
  book doesn't already have one.

## Usage

Select one or more books with an EPUB, click the **Extract Metadata** toolbar button, review the
preview, and confirm. Then run FanFicFare's **Update Calibre Metadata from Saved Metadata Column**
action to update your library metadata.

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
