"""
Orchestrates the source-priority cascade: runs each extractor tier, merges
their output (earliest tier supplying a field wins), maps FFF-shaped
per-site vocabulary, and derives a handful of cheap extra fields FFF itself
also computes at read-time. Produces the `fields` dict serialize.py turns
into the Saved Metadata column value.

Tier order (per the plan): OPF baseline, FFF title page, AO3 front matter,
generic link-scan fallback. In practice tiers 2 and 3 are mutually
exclusive (a given EPUB has either FFF's title page or AO3's native
preface, not both), so their relative order rarely matters -- OPF is kept
first because it's the most universally reliable source for
title/authors/language/description when present.
"""
import datetime
import re
from urllib.parse import quote
from zipfile import ZipFile

from .extractors.ao3_frontmatter import extract_ao3_frontmatter
from .extractors.fallback_link_scan import extract_story_url_fallback
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
    'chapters': 'numChapters',
    'words': 'numWords',
    'publisher': 'site',
    'summary': 'description',
}

LIST_KEYS = {
    'warnings', 'fandoms', 'ships', 'characters', 'freeformtags',
    'ao3categories', 'category', 'genre',
    # per fanficfare/configurable.py get_valid_list_entries() -- these are
    # always list-type even for a single value (verified: the real sample
    # wraps a single author in <ul><li id="author">).
    'author', 'authorId', 'authorUrl',
}

_WORKS_URL_RE = re.compile(r'/works/(\d+)')
_TAG_RE = re.compile(r'<[^>]+>')
_DATE_FORMATS = ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d')
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


def _map_titlepage(titlepage):
    result = {}
    if not titlepage:
        return result
    if titlepage.get('storyUrl'):
        result['storyUrl'] = titlepage['storyUrl']
    if titlepage.get('title'):
        result['title'] = titlepage['title']
    for label, value in (titlepage.get('label_entries') or {}).items():
        key = TITLEPAGE_LABEL_TO_KEY.get(label.strip().lower())
        if key:
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
        fallback_url = extract_story_url_fallback(zf)

    titlepage_mapped = _map_titlepage(titlepage)
    ao3_fields = dict(ao3 or {})

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
    if opf.get('dc_source'):
        opf_fields['storyUrl'] = opf['dc_source']
    fanficfare_uid = opf.get('fanficfare_uid')
    if fanficfare_uid:
        opf_fields.setdefault('site', fanficfare_uid.get('site'))
        opf_fields.setdefault('storyId', fanficfare_uid.get('storyid'))

    fallback_fields = {'storyUrl': fallback_url} if fallback_url else {}

    fields = _merge(opf_fields, titlepage_mapped, ao3_fields, fallback_fields)

    source_tiers = {}
    for tier_name, tier_fields in (
        ('opf', opf_fields), ('fff_titlepage', titlepage_mapped),
        ('ao3_frontmatter', ao3_fields), ('fallback_link_scan', fallback_fields),
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
        m = _WORKS_URL_RE.search(story_url)
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
        fields.setdefault('authorHTML', "<a class='authorlink' href='%s'>%s</a>" % (
            author_url_scalar, author_name))

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
    for key in ('datePublished', 'dateUpdated', 'dateCreated'):
        if key in fields:
            parsed = _parse_date(fields[key])
            if parsed is not None:
                fields[key] = parsed

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
    for key in ('numChapters', 'numWords'):
        value = fields.get(key)
        if isinstance(value, str):
            digits = value.replace(',', '').strip()
            if digits.isdigit():
                fields[key] = int(digits)
