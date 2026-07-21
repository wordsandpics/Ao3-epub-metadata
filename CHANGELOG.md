# Changelog

## [0.1.0-beta] - 2026-07-21

Initial public beta release.

### Added
- **Save all extracted metadata** — writes recovered metadata into a Saved Metadata custom
  column in FanFicFare's own native format, ready for FFF's "Update Calibre Metadata from Saved
  Metadata Column" action.
- **Update standard Calibre metadata** — writes directly to Title, Author, Tags, Series and
  Comments using FanFicFare's default AO3 field-composition rules, no FFF round trip required.
- **Update custom columns** — a configurable mapping from recovered metadata fields to your own
  custom columns.
- **Extract story status from anthology** — a separate action for epubmerge-bundled anthology
  EPUBs (e.g. a downloaded AO3 series), recovering each individual fic's own completion status
  instead of just the bundle's single aggregate status, and writing a per-fic breakdown into a
  column you choose.
- Toolbar dropdown for quick access to both actions plus settings, without needing to select
  books first.
- Preview dialog before any writes, with per-book opt-out, for every mode above.
