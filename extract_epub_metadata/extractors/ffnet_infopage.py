"""
Native fanfiction.net story-info HTML, scraped verbatim by WebToEpub
(https://github.com/dteviot/WebToEpub) into its own "Information" page --
confirmed against tests/fixtures/Isolation - Bex-chan.epub. Unlike
fichub.net's own paraphrased front matter (see fff_titlepage.py's
<p>Label: value</p> handling), this is fanfiction.net's actual website
markup (a `<div id="profile_top">`), including its own long-standing
"story stats" line:

    Rated: Fiction M - English - Romance/Angst - Hermione G., Draco M. -
    Chapters: 49 - Words: 284,050 - Reviews: 19,021 - Favs: 39,196 -
    Follows: 20,504 - Updated: 1/5/2020, 3:12:37 AM -
    Published: 9/2/2010, 2:43:45 PM - Status: Complete - id: 6291747

Language/genre/characters have NO labels here -- they're three bare
values in a fixed position, right after "Rated: <rating>" and before
"Chapters:". Only trusted when exactly three such unlabeled segments are
found (see _split_stats_line): if a fic has, say, no genre tagged, we
can't tell which of the three slots is missing, so all three are left
unset in that case rather than risk a wrong assignment. Every other
(labeled) field is recovered either way, regardless of this.

The fandom itself isn't in that stats line at all -- it's fanfiction.net's
own breadcrumb, a sibling of `#profile_top` rather than inside it:
`<div id="pre_story_links">...<a>Books</a> &gt; <a>Harry Potter</a></div>`.
The last link's text is the fandom (confirmed against
tests/fixtures/isolation.epub, a single-fandom story). For a crossover,
fanfiction.net's breadcrumb has more segments ("Books > A > Crossover >
B") -- only the last is taken here since there's no fixture to verify
crossover handling against; that's a known, deliberate limitation rather
than a guess.
"""
import re

from ._epubxml import find_all, find_first, parse_opf, parse_xhtml, spine_item_paths, text_content

_LABELED_SEGMENT_RE = re.compile(r'^([A-Za-z][\w \-/]{0,30}):\s*(.+)$')
_AUTHOR_LINK_RE = re.compile(r'/u/(\d+)/')
_WS_RE = re.compile(r'\s+')

# Reviews/favs/follows deliberately unmapped -- live-only engagement
# stats, same treatment as AO3's hits/kudos/bookmarks elsewhere in this
# plugin (they're still scraped as labeled segments, just discarded).
_LABEL_TO_KEY = {
    'rated': 'rating',
    'chapters': 'numChapters',
    'words': 'numWords',
    'updated': 'dateUpdated',
    'published': 'datePublished',
    'status': 'status',
    'id': 'storyId',
}


def _normalize_ws(text):
    return _WS_RE.sub(' ', text).strip()


def _find_profile_top(root):
    for div in find_all(root, 'div'):
        if (div.get('id') or '') == 'profile_top':
            return div
    return None


def _find_fandom(root):
    for div in find_all(root, 'div'):
        if (div.get('id') or '') != 'pre_story_links':
            continue
        links = [a for a in find_all(div, 'a') if text_content(a).strip()]
        if links:
            return text_content(links[-1]).strip()
    return None


def _find_stats_span(profile_top):
    for span in find_all(profile_top, 'span'):
        if 'xgray' in (span.get('class') or '').split():
            return span
    return None


def _find_summary(profile_top):
    # fanfiction.net gives the summary div no distinguishing class/id of
    # its own -- the longest non-empty <div> *inside* profile_top is it
    # (the only other <div> there is an empty layout spacer). find_all()
    # yields the element passed in as well as its descendants (ElementTree
    # .iter() semantics), so profile_top itself -- whose flattened text is
    # everything, title/byline/stats included -- must be excluded, not
    # just skipped by emptiness.
    best = ''
    for div in find_all(profile_top, 'div'):
        if div is profile_top:
            continue
        text = _normalize_ws(text_content(div))
        if len(text) > len(best):
            best = text
    return best or None


def _split_stats_line(text):
    """Returns (labeled_fields, unlabeled_segments). unlabeled_segments is
    only ever the run of bare values between "Rated: ..." and the next
    labeled segment (normally "Chapters:")."""
    segments = [_normalize_ws(s) for s in text.split(' - ') if s.strip()]
    if not segments:
        return {}, []

    result = {}
    m = _LABELED_SEGMENT_RE.match(segments[0])
    rest = segments[1:] if (m and m.group(1).strip().lower() == 'rated') else segments
    if m and m.group(1).strip().lower() == 'rated':
        result['rating'] = m.group(2).strip()

    i = 0
    unlabeled = []
    while i < len(rest) and not _LABELED_SEGMENT_RE.match(rest[i]):
        unlabeled.append(rest[i])
        i += 1

    for segment in rest[i:]:
        seg_match = _LABELED_SEGMENT_RE.match(segment)
        if not seg_match:
            continue
        key = _LABEL_TO_KEY.get(seg_match.group(1).strip().lower())
        if not key:
            continue
        value = seg_match.group(2).strip()
        if key == 'status':
            # fanfiction.net's own casing ("Status: Complete") differs
            # from the canonical 'Completed'/'In-Progress' vocabulary used
            # elsewhere (calibre_fields.py's STATUS_COMPLETE_KEY,
            # anthology.py) -- same two-way normalization already applied
            # to fichub's own lowercase "complete" in mapping.py.
            value = 'Completed' if value.lower().startswith('complete') else 'In-Progress'
        result[key] = value

    return result, unlabeled


def extract_ffnet_infopage(zf):
    opf_root, opf_path = parse_opf(zf)
    if opf_root is None:
        return None

    for path in spine_item_paths(zf, opf_root, opf_path):
        root = parse_xhtml(zf, path)
        if root is None:
            continue
        profile_top = _find_profile_top(root)
        if profile_top is None:
            continue

        result = {}

        # sibling of profile_top, not nested inside it -- search the
        # whole document, not just profile_top.
        fandom = _find_fandom(root)
        if fandom:
            result['fandoms'] = [fandom]
            # FanFicFare's own [archiveofourown.org] section composites
            # Tags category from 'category, fandoms' -- but fanfiction.net
            # has no such override, so FFF's global default just uses the
            # raw 'category' key directly for it (per its own
            # defaults.ini comment: "Sometimes Harry Potter is a category
            # and Fantasy a genre. (fanfiction.net)"). Without this, FFF's
            # own "Update Calibre Metadata from Saved Metadata Column"
            # action recomputes Tags without ever seeing the fandom at
            # all -- confirmed as the cause of a real bug report where
            # running that action deleted the fandom from Tags. 'fandoms'
            # is kept too, for this plugin's own Mode 2/3 writes.
            result['category'] = [fandom]

        b = find_first(profile_top, 'b')
        if b is not None:
            title_text = text_content(b).strip()
            if title_text:
                result['title'] = title_text

        for a in find_all(profile_top, 'a'):
            m = _AUTHOR_LINK_RE.search(a.get('href') or '')
            if m:
                name = text_content(a).strip()
                if name:
                    result['author'] = [name]
                    result['authorId'] = [m.group(1)]
                    result['authorUrl'] = [(a.get('href') or '').strip()]
                break

        stats_span = _find_stats_span(profile_top)
        if stats_span is not None:
            labeled, unlabeled = _split_stats_line(_normalize_ws(text_content(stats_span)))
            result.update(labeled)
            if len(unlabeled) == 3:
                language, genre, characters = unlabeled
                if language:
                    result['language'] = language
                if genre:
                    result['genre'] = [genre]
                if characters:
                    result['characters'] = [c.strip() for c in characters.split(',') if c.strip()]

        summary = _find_summary(profile_top)
        if summary:
            result['description'] = summary

        return result if result else None

    return None
