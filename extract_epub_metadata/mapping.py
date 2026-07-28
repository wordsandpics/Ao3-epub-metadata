"""
Orchestrates the source-priority cascade: runs each extractor tier, merges
their output (earliest tier supplying a field wins), maps FFF-shaped
per-site vocabulary, and derives a handful of cheap extra fields FFF itself
also computes at read-time. Produces the `fields` dict serialize.py turns
into the Saved Metadata column value.

Tier order (per the plan): OPF baseline, FFF title page, AO3 front matter,
fanfiction.net's own native info page (as scraped verbatim by WebToEpub),
generic link-scan fallback. In practice tiers 2/3/3b are mutually
exclusive (a given EPUB has at most one of FFF's title page, AO3's native
preface, or fanfiction.net's native info page), so their relative order
rarely matters -- OPF is kept first because it's the most universally
reliable source for title/authors/language/description when present.
"""
import datetime
import re
from urllib.parse import quote
from zipfile import ZipFile

from .extractors.ao3_frontmatter import extract_ao3_frontmatter
from .extractors.fallback_link_scan import extract_story_url_fallback
from .extractors.ffnet_infopage import extract_ffnet_infopage
from .extractors.fff_titlepage import extract_fff_titlepage
from .extractors.opf import extract_opf

# key -> (siteabbrev, )  -- 'site' itself already holds the domain, which is
# also what FFF uses as the human-facing "Publisher" value, so there's no
# separate publisher key (verified: the real sample has no id="publisher").
SITE_ABBREV = {
    'archiveofourown.org': 'ao3',
    'fanfiction.net': 'ffnet',
}

LANGCODES = {
    'english': 'en', 'french': 'fr', 'spanish': 'es', 'german': 'de',
    'japanese': 'ja', 'chinese': 'zh', 'italian': 'it', 'portuguese': 'pt',
    'russian': 'ru', 'korean': 'ko', 'dutch': 'nl', 'polish': 'pl',
}

# Best-effort label -> key map for FFF title-page entries (tier 2), using
# FFF's default English labels (fanficfare/defaults.ini). personal.ini
# label customization is out of scope for v1 -- unrecognized labels are
# just skipped rather than guessed at.
TITLEPAGE_LABEL_TO_KEY = {
    'category': 'category',
    'genre': 'genre',
    'language': 'language',
    'characters': 'characters',
    'ships': 'ships',
    'relationships': 'ships',
    'status': 'status',
    'published': 'datePublished',
    'updated': 'dateUpdated',
    'packaged': 'dateCreated',
    'rating': 'rating',
    'warnings': 'warnings',
    'archive warning': 'warnings',
    'chapters': 'numChapters',
    'words': 'numWords',
    'publisher': 'site',
    'summary': 'description',
    # AO3's own raw (pre-composite) vocabulary -- some title-page variants
    # use these separate labels instead of FFF's composite "Category"/
    # "Genre" lines (confirmed against tests/fixtures/sigh_no_more.epub,
    # which has none of category/genre but does have these).
    'fandom': 'fandoms',
    'fandoms': 'fandoms',
    'additional tags': 'freeformtags',
    'categories': 'ao3categories',
    # fanfiction.net's own label for the same concept as AO3/FFF's
    # "Rating" (confirmed against tests/fixtures/hunted.epub, via
    # fichub.net's "Rated: Fiction M - Language: ... - ..." composite
    # line -- see _split_composite_label_value below).
    'rated': 'rating',
}

# Deliberately no entries for 'reviews'/'favs'/'follows' -- fanfiction.net's
# live engagement stats, same "don't fabricate a value only a live fetch
# could keep current" treatment already applied to AO3's hits/kudos/
# bookmarks. They still get scraped as label:value pairs by
# _split_composite_label_value below; having no key mapping here is what
# makes them silently dropped, no extra filtering code needed.

LIST_KEYS = {
    'warnings', 'fandoms', 'ships', 'characters', 'freeformtags',
    'ao3categories', 'category', 'genre',
    # per fanficfare/configurable.py get_valid_list_entries() -- these are
    # always list-type even for a single value (verified: the real sample
    # wraps a single author in <ul><li id="author">).
    'author', 'authorId', 'authorUrl',
}

_WORKS_URL_RE = re.compile(r'/works/(\d+)')
# fanfiction.net's own story-URL shape, e.g. ".../s/5853767/1/Hunted"
# (confirmed against tests/fixtures/hunted.epub).
_FFNET_STORY_ID_RE = re.compile(r'/s/(\d+)')
_TAG_RE = re.compile(r'<[^>]+>')
# "Label: value" for one segment of a composite line, e.g. fanfiction.net's
# own "Rated: Fiction M - Language: English - Genre: ... - Reviews: ..."
# (confirmed against tests/fixtures/hunted.epub). Deliberately the same
# shape as _PARA_LABEL_RE in fff_titlepage.py, just applied per-segment
# here rather than per-<p>.
_COMPOSITE_SEGMENT_RE = re.compile(r'^([A-Za-z][\w \-/]{0,30}):\s*(.+)$')
# Total is often "?" for an ongoing fic whose final chapter count isn't
# known yet (confirmed against tests/fixtures/crimson supernova -
# serenadewave.epub's "Chapters: 41/?") -- status can't be derived from
# that, but the current chapter count is still perfectly recoverable.
_CHAPTERS_SLASH_RE = re.compile(r'^\s*(\d+)\s*/\s*(\d+|\?)\s*$')
# FFF's own default per-key date formats differ: dateCreated ("Packaged")
# defaults to "%Y-%m-%d %H:%M:%S" (space-separated, with time), while
# datePublished/dateUpdated default to date-only "%Y-%m-%d". Both are also
# personal.ini-configurable, so this can never be exhaustive -- see
# _parse_date's caller for what happens when none of these match.
_DATE_FORMATS = (
    '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d',
    # fanfiction.net's own native date rendering, as scraped verbatim by
    # WebToEpub (confirmed against tests/fixtures/Isolation - Bex-
    # chan.epub's "Updated: 1/5/2020, 3:12:37 AM").
    '%m/%d/%Y, %I:%M:%S %p',
)
_TZ_SUFFIX_RE = re.compile(r'([+-]\d{2}:\d{2}|Z)$')


def _coerce_for_key(key, value):
    if key in LIST_KEYS and isinstance(value, str):
        parts = [p.strip() for p in re.split(r',\s*', value) if p.strip()]
        return parts or [value]
    return value


def _strip_html(text):
    if not text:
        return text
    return _TAG_RE.sub('', text).strip()


def _parse_date(value):
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value
    if not value:
        return None
    text = str(value).strip()
    text = _TZ_SUFFIX_RE.sub('', text)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _split_composite_label_value(value):
    """
    Some sites pack several 'Label: value' pairs into one line, separated
    by ' - ' -- e.g. fanfiction.net's own (via fichub.net) "Rated: Fiction
    M - Language: English - Genre: Romance/Mystery - Reviews: 3,176"
    (confirmed against tests/fixtures/hunted.epub). Splits that into the
    first label's own direct value plus a dict of the embedded sub-labels.

    Only activates when at least one segment after splitting on ' - '
    actually looks like its own 'Label: value' pair. If none do, the
    value is returned completely untouched (empty sub_entries) -- this is
    what keeps it from misfiring on something like a freeform-tags blob
    that happens to contain ' - ' inside one tag's own text (e.g.
    "Alternate Universe - No Powers, ..."), confirmed safe against
    tests/fixtures/crimson_supernova.epub.
    """
    segments = [s.strip() for s in value.split(' - ') if s.strip()]
    if not segments:
        return value, {}
    sub_entries = {}
    for segment in segments[1:]:
        m = _COMPOSITE_SEGMENT_RE.match(segment)
        if m:
            sub_entries[m.group(1).strip()] = m.group(2).strip()
    if not sub_entries:
        return value, {}
    return segments[0], sub_entries


def _map_titlepage(titlepage):
    result = {}
    if not titlepage:
        return result
    if titlepage.get('storyUrl'):
        result['storyUrl'] = titlepage['storyUrl']
    if titlepage.get('title'):
        result['title'] = titlepage['title']

    entries = dict(titlepage.get('label_entries') or {})
    for label in list(entries):
        head, sub_entries = _split_composite_label_value(entries[label])
        if sub_entries:
            entries[label] = head
            for sub_label, sub_value in sub_entries.items():
                # An explicit top-level "Label: value" line always wins
                # over the same label discovered inside a composite blob.
                entries.setdefault(sub_label, sub_value)

    for label, value in entries.items():
        key = TITLEPAGE_LABEL_TO_KEY.get(label.strip().lower())
        if not key:
            continue
        # "Chapters: 1/1" (some title-page variants use AO3's n/total
        # notation instead of FFF's own plain current-chapter-count) --
        # confirmed against tests/fixtures/sigh_no_more.epub. Recover
        # numChapters from the numerator and derive status as a fallback,
        # the same way ao3_frontmatter.py's _parse_stats() already does
        # for AO3's own preface -- an explicit "Status:" line elsewhere on
        # the page still wins via setdefault, regardless of scan order.
        if key == 'numChapters':
            m = _CHAPTERS_SLASH_RE.match(str(value))
            if m:
                n, total = m.group(1), m.group(2)
                result['numChapters'] = n
                result['chapterslashtotal'] = '%s/%s' % (n, total)
                if total != '?':
                    result.setdefault(
                        'status', 'Completed' if n == total else 'In-Progress')
                continue
        if key == 'status':
            # Sites/tools spell this differently (fichub's own
            # fanfiction.net template uses lowercase "complete" --
            # confirmed against tests/fixtures/hunted.epub), but it's
            # only ever one of two states, so a two-way classification
            # covers every variant without guessing at exact spellings
            # for the "not complete" case.
            result['status'] = ('Completed' if str(value).strip().lower().startswith('complete')
                                 else 'In-Progress')
            continue
        result[key] = _coerce_for_key(key, value)
    return result


def _merge(*tiers):
    merged = {}
    for tier in tiers:
        for key, value in (tier or {}).items():
            if key in ('label_entries', 'subjects', 'authors', 'identifiers',
                       'dc_source', 'fanficfare_uid', 'pubdate'):
                continue
            if key not in merged and value not in (None, '', [], ()):
                merged[key] = value
    return merged


def extract_fields(epub_stream):
    """
    epub_stream: path or file-like object openable as a zip.
    Returns (fields, source_tiers): `fields` is ready for
    serialize.serialize_saved_metadata(); `source_tiers` maps each
    populated key to the tier name that supplied it, for the preview
    dialog / diagnostics.
    """
    with ZipFile(epub_stream) as zf:
        opf = extract_opf(zf)
        titlepage = extract_fff_titlepage(zf)
        ao3 = extract_ao3_frontmatter(zf)
        ffnet_info = extract_ffnet_infopage(zf)
        fallback_url = extract_story_url_fallback(zf)

    titlepage_mapped = _map_titlepage(titlepage)
    ao3_fields = dict(ao3 or {})
    ffnet_fields = dict(ffnet_info or {})

    opf_fields = {}
    if opf.get('title'):
        opf_fields['title'] = opf['title']
    if opf.get('authors'):
        opf_fields['author'] = opf['authors']
    if opf.get('language'):
        # dc:language is a code (e.g. "en"), not a display name -- FFF's
        # 'language' key holds the display name ("English"); the code
        # belongs in 'langcode'. AO3/titlepage tiers supply the display
        # name when available; this is just the OPF-only fallback.
        opf_fields['langcode'] = opf['language']
    if opf.get('description'):
        opf_fields['description'] = _strip_html(opf['description'])
    # An explicit url/uri-scheme identifier is preferred over dc:source --
    # some tools (WebToEpub, confirmed against tests/fixtures/Isolation -
    # Bex-chan.epub) write one <dc:source> per chapter *plus* one for the
    # cover image, in which case the first one (what dc:source used to
    # fall back to unconditionally) can easily be the cover image URL,
    # not the story. Confirmed harmless for every other fixture: FFF's
    # own EPUBs already carry the identical URL in both places.
    identifier_url = None
    for scheme in ('url', 'uri'):
        candidate = (opf.get('identifiers') or {}).get(scheme)
        if candidate and candidate.startswith(('http://', 'https://')):
            identifier_url = candidate
            break
    if identifier_url:
        opf_fields['storyUrl'] = identifier_url
    elif opf.get('dc_source'):
        opf_fields['storyUrl'] = opf['dc_source']
    fanficfare_uid = opf.get('fanficfare_uid')
    if fanficfare_uid:
        opf_fields.setdefault('site', fanficfare_uid.get('site'))
        opf_fields.setdefault('storyId', fanficfare_uid.get('storyid'))

    fallback_fields = {'storyUrl': fallback_url} if fallback_url else {}

    fields = _merge(opf_fields, titlepage_mapped, ao3_fields, ffnet_fields, fallback_fields)

    source_tiers = {}
    for tier_name, tier_fields in (
        ('opf', opf_fields), ('fff_titlepage', titlepage_mapped),
        ('ao3_frontmatter', ao3_fields), ('ffnet_infopage', ffnet_fields),
        ('fallback_link_scan', fallback_fields),
    ):
        for key in tier_fields:
            if fields.get(key) == tier_fields[key]:
                source_tiers.setdefault(key, tier_name)

    _derive_fields(fields)
    _finalize_dates(fields)
    _finalize_numerics(fields)

    return fields, source_tiers


def _derive_fields(fields):
    story_url = fields.get('storyUrl')
    site = fields.get('site')
    if not site and story_url:
        m = re.match(r'^https?://(?:www\.)?([^/]+)/', story_url)
        if m:
            site = m.group(1)
            fields['site'] = site
    if not fields.get('storyId') and story_url:
        m = _WORKS_URL_RE.search(story_url) or _FFNET_STORY_ID_RE.search(story_url)
        if m:
            fields['storyId'] = m.group(1)

    if site and site in SITE_ABBREV:
        fields.setdefault('siteabbrev', SITE_ABBREV[site])

    fields.setdefault('sectionUrl', story_url)

    author = fields.get('author')
    if author:
        author_list = author if isinstance(author, list) else [author]
        fields['author'] = author_list
        author_name = ', '.join(author_list)
        fields.setdefault('byline', author_name)

        # authorId/authorUrl before authorHTML, which needs the URL.
        if site == 'archiveofourown.org' and len(author_list) == 1:
            fields.setdefault('authorId', [author_list[0]])
            fields.setdefault('authorUrl', ['https://archiveofourown.org/users/%s/pseuds/%s' % (
                quote(author_list[0]), quote(author_list[0]))])
        elif fields.get('authorUrl') and not isinstance(fields['authorUrl'], list):
            fields['authorUrl'] = [fields['authorUrl']]

        author_url_scalar = (fields.get('authorUrl') or [''])[0]
        if author_url_scalar:
            fields.setdefault('authorHTML', "<a class='authorlink' href='%s'>%s</a>" % (
                author_url_scalar, author_name))
        else:
            # No recovered author URL (common for non-AO3 sites, e.g.
            # fanfiction.net via fichub.net -- confirmed against
            # tests/fixtures/hunted.epub) -- plain name rather than a
            # broken <a href=''> link.
            fields.setdefault('authorHTML', author_name)

    title = fields.get('title')
    if title and story_url:
        fields.setdefault('titleHTML', "<a class='titlelink' href='%s'>%s</a>" % (story_url, title))

    # 'language' is the display name ("English"); 'langcode' is the ISO
    # code. Whichever we have, backfill the other as best-effort.
    if not fields.get('langcode') and fields.get('language'):
        fields['langcode'] = LANGCODES.get(str(fields['language']).strip().lower())
    if not fields.get('language') and fields.get('langcode'):
        fields['language'] = fields['langcode']
    if not fields.get('langcode'):
        fields.pop('langcode', None)

    fields.setdefault('formatname', 'epub')
    fields.setdefault('formatext', '.epub')
    fields.setdefault('dateCreated', datetime.datetime.now())


def _finalize_dates(fields):
    # A field that stays a plain string here gets serialized without the
    # 'datetime' class (see serialize.py), so load_html_metadata() won't
    # datetime-parse it either -- it'll load as a plain string, and FFF's
    # own downstream code (e.g. strftime() calls when composing the title
    # page) then crashes on it. Since FFF's date formats are
    # personal.ini-configurable, _DATE_FORMATS can never be guaranteed to
    # match every source -- so an unparseable value must never be left in
    # place as a raw string: drop it (or, for dateCreated, fall back to
    # now()) rather than risk that crash downstream in FFF.
    for key in ('datePublished', 'dateUpdated', 'dateCreated'):
        if key not in fields:
            continue
        value = fields[key]
        if isinstance(value, (datetime.date, datetime.datetime)):
            continue
        parsed = _parse_date(value)
        if parsed is not None:
            fields[key] = parsed
        elif key == 'dateCreated':
            fields[key] = datetime.datetime.now()
        else:
            del fields[key]

    date_updated = fields.get('dateUpdated')
    if isinstance(date_updated, (datetime.date, datetime.datetime)) and 'lastupdate' not in fields:
        fields['lastupdate'] = [
            'Last Update Year/Month: %s' % date_updated.strftime('%Y/%m'),
            'Last Update: %s' % date_updated.strftime('%Y/%m/%d'),
        ]


def _finalize_numerics(fields):
    # FFF stores these as real ints internally (getMetadata() applies
    # comma-formatting only at *read* time via commaGroups()) -- serialize.py
    # needs an actual int to emit the 'int' class dump_html_metadata() uses,
    # which is what load_html_metadata() checks for on the way back in.
    # Same drop-rather-than-corrupt rule as _finalize_dates(): a title page
    # can hand us something that never resolves to a clean int (e.g.
    # "41/?" for an ongoing fic with an unknown final chapter count --
    # _map_titlepage's slash handling already recovers the numerator for
    # the common case, but this is the backstop for anything that still
    # gets through). Leaving a raw non-numeric string in place crashed
    # Calibre outright once it reached an int-typed custom column via
    # Mode 3 (calibre/db/write.py's adapt_number does a bare int(value)).
    for key in ('numChapters', 'numWords'):
        if key not in fields:
            continue
        value = fields[key]
        if isinstance(value, int):
            continue
        digits = str(value).replace(',', '').strip()
        if digits.isdigit():
            fields[key] = int(digits)
        else:
            del fields[key]
