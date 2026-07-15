"""
Tier 1: standard OPF / Dublin Core metadata, plus FanFicFare-specific
markers that live in the OPF but aren't part of plain Dublin Core:
- dc:source -- FFF writes the original story URL here (fanficfare/epubutils.py::get_dcsource).
- a `fanficfare-uid:{site}-u{authorId}-s{storyId}` identifier -- lets us
  recover site/authorId/storyId even when dc:source is absent.

This module is pure stdlib and works standalone (for tests) or inside
Calibre. In the real plugin, action.py additionally calls Calibre's own
calibre.ebooks.metadata.epub.get_metadata() for the richer/authoritative
standard-field parse; this module's `title`/`authors`/etc. are the
fallback used when that isn't available (or to fill any gaps).
"""
import re

from ._epubxml import find_all, find_first, parse_opf, text_content

OPF_SCHEME_ATTR = '{http://www.idpf.org/2007/opf}scheme'

_FANFICFARE_UID_RE = re.compile(
    r'^fanficfare-uid:(?P<site>[^-]+)-u(?P<authorid>[^-]+)-s(?P<storyid>.+)$')


def extract_opf(zf):
    root, opf_path = parse_opf(zf)
    if root is None:
        return {}
    metadata_el = find_first(root, 'metadata')
    if metadata_el is None:
        return {}

    result = {}

    titles = [text_content(e).strip() for e in find_all(metadata_el, 'title')]
    titles = [t for t in titles if t]
    if titles:
        result['title'] = titles[0]

    authors = [text_content(e).strip() for e in find_all(metadata_el, 'creator')]
    authors = [a for a in authors if a]
    if authors:
        result['authors'] = authors

    langs = [text_content(e).strip() for e in find_all(metadata_el, 'language')]
    langs = [l for l in langs if l]
    if langs:
        result['language'] = langs[0]

    pubs = [text_content(e).strip() for e in find_all(metadata_el, 'publisher')]
    pubs = [p for p in pubs if p]
    if pubs:
        result['publisher'] = pubs[0]

    descs = [text_content(e).strip() for e in find_all(metadata_el, 'description')]
    descs = [d for d in descs if d]
    if descs:
        result['description'] = descs[0]

    subjects = [text_content(e).strip() for e in find_all(metadata_el, 'subject')]
    subjects = [s for s in subjects if s]
    if subjects:
        result['subjects'] = subjects

    dates = [text_content(e).strip() for e in find_all(metadata_el, 'date')]
    dates = [d for d in dates if d]
    if dates:
        result['pubdate'] = dates[0]

    identifiers = {}
    for ident in find_all(metadata_el, 'identifier'):
        scheme = ident.get(OPF_SCHEME_ATTR) or ident.get('scheme') or ''
        value = text_content(ident).strip()
        if value:
            identifiers[scheme.lower()] = value
    if identifiers:
        result['identifiers'] = identifiers

    sources = [text_content(e).strip() for e in find_all(metadata_el, 'source')]
    sources = [s for s in sources if s]
    if sources:
        result['dc_source'] = sources[0]

    for value in identifiers.values():
        m = _FANFICFARE_UID_RE.match(value)
        if m:
            result['fanficfare_uid'] = m.groupdict()
            break

    return result
