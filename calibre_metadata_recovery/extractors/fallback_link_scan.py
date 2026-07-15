"""
Tier 4: last-resort story-URL recovery. Scans content documents (title
page first, mirroring fanficfare/epubutils.py::get_story_url_from_zip_html)
for the first link matching a recognized fanfic-site URL pattern.

Only recovers a URL (enough to set the Calibre `identifiers` field so
FanFicFare's own action can pick the right adapter) -- no other metadata.
Extend _SITE_PATTERNS as more sites are supported.
"""
import re

from ._epubxml import find_all, parse_opf, parse_xhtml, spine_item_paths

_SITE_PATTERNS = [
    re.compile(r'^https?://(www\.)?archiveofourown\.org/works/\d+', re.I),
    re.compile(r'^https?://(www\.|m\.)?fanfiction\.net/s/\d+', re.I),
]


def _is_recognized_url(href):
    return any(p.match(href) for p in _SITE_PATTERNS)


def extract_story_url_fallback(zf):
    opf_root, opf_path = parse_opf(zf)
    if opf_root is None:
        return None

    paths = spine_item_paths(zf, opf_root, opf_path)
    paths = sorted(paths, key=lambda p: 0 if 'title_page' in p.lower() else 1)

    for path in paths:
        root = parse_xhtml(zf, path)
        if root is None:
            continue
        for a in find_all(root, 'a'):
            href = (a.get('href') or '').strip()
            if href.startswith('http') and _is_recognized_url(href):
                return href

    return None
