# Extract Epub Metadata

A Calibre plugin that extracts [FanFicFare](https://github.com/JimmXinu/FanFicFare)-compatible
metadata from an EPUB already in your library, for situations where FanFicFare itself can't
(re-)download the story — Cloudflare, deleted works, manual/browser downloads, archived copies.

It reads the EPUB, recovers whatever metadata it can (title, author, fandom, relationships,
characters, tags, rating, warnings, word/chapter counts, dates, story URL...), and writes it into
a configured "Saved Metadata" custom column in FanFicFare's own format. From there, FanFicFare's
existing **"Update Calibre Metadata from Saved Metadata Column"** action takes over unchanged —
`personal.ini` replacements, custom-column mappings, and cover generation all keep working exactly
as they do for a normal download.

This plugin deliberately does not re-implement any of FanFicFare's own metadata processing. It
only extracts, maps field names, and writes the column — FanFicFare stays the single source of
truth for how that metadata turns into your library's actual Title/Tags/Comments/custom columns.

## How it works

For each selected book, metadata is recovered from a cascade of sources (richest first):

1. Standard EPUB/OPF metadata (title, authors, language, description, tags, `dc:source`).
2. A FanFicFare-generated title page, if the EPUB was originally produced by FanFicFare.
3. AO3's own native front-matter preface, if the EPUB was downloaded directly from
   [Archive of Our Own](https://archiveofourown.org).
4. A generic scan for the first recognized fanfic-site link, as a last-resort way to at least
   recover the story URL.

Fields from an earlier tier win; later tiers only fill gaps. The plugin also writes a `url`
identifier onto the book (only if one isn't already set) when it recovers a story URL, since
FanFicFare needs that to pick the right site adapter when it later reads the Saved Metadata
column back.

The plugin only ever writes to the configured Saved Metadata column and, optionally, a missing
`url`/`uri` identifier — never to Title/Author/Tags/Comments/Series/etc. directly.

## Installing

```sh
# from this directory
/Applications/calibre.app/Contents/MacOS/calibre-customize -b calibre_metadata_recovery
```

(On Linux/Windows, use whichever `calibre-customize` is on your `PATH`.) Or, in the Calibre GUI:
Preferences → Plugins → Load plugin from file, pointing at a zipped copy of the
`calibre_metadata_recovery/` directory.

## Configuring

In Preferences → Plugins → Extract Epub Metadata → Customize plugin:

- **Saved Metadata Column** — a Long Text ("comments") custom column. Point this at the same
  column FanFicFare's own "Saved Metadata Column" setting uses.
- **Overwrite existing column value** — off by default; books with an existing value are skipped.
- **Preview before writing** — on by default; review recovered fields before anything is written.
- **Add missing story-URL identifier** — on by default; only ever adds a `url` identifier when
  the book doesn't already have one.

## Usage

Select one or more books with an EPUB format, click the "Extract Metadata" toolbar button, review
the preview, and confirm. Then run FanFicFare's own "Update Calibre Metadata from Saved Metadata
Column" action as usual.

## Development

```sh
python3 -m unittest discover -s tests -v
```

The test suite is stdlib-only (`unittest`, `xml.etree.ElementTree`) and runs without Calibre
installed, using a minimal stub in `tests/calibre_stub/` so `calibre_metadata_recovery/__init__.py`
can be imported outside a real Calibre environment. It runs against real fixtures in
`tests/fixtures/`, including an actual AO3-downloaded EPUB and a real Saved Metadata column value.

One test (`test_round_trips_through_fanficfare_load_html_metadata`) additionally verifies against
FanFicFare's own installed `load_html_metadata()` when available, and skips cleanly otherwise.
