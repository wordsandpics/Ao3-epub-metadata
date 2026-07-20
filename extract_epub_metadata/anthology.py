"""
"Extract story status from anthology": a second, independent action in
this plugin (not part of the extract_fields()/mapping.py pipeline used by
the main "Extract Metadata" action). FanFicFare can bundle several
separately-downloaded fics into one EPUB via `epubmerge`; the bundle's own
aggregate metadata only ever carries ONE completion status for the whole
thing (In-Progress if *any* included fic is unfinished). This module
recovers each individual fic's own status instead.

Verified directly against a real epubmerge-produced anthology (7 fics,
fics 1-6 Completed, fic 7 In-Progress) via calibre-debug and direct
inspection -- see the plan's "Extract story status from anthology"
section for the full trail. Deliberately NOT reusing
extractors/fff_titlepage.py's extract_fff_titlepage() as-is: that function
returns on the *first* spine match, which is exactly the bug this module
exists to avoid. It reuses that function's underlying <b>label</b>:value
scanning approach (tolerant of missing/reordered fields -- confirmed
necessary, since the in-progress fic's title page omits "Published" and
orders fields differently from the completed fics' pages), applied to
every fic-shaped spine group instead of stopping at the first.

is_anthology()/extract_fic_records()/format_summary() are pure (no
Calibre import) and unit-testable the same way as mapping.py/
calibre_fields.py.
"""
import datetime
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from .extractors._epubxml import find_all, find_first, parse_opf, parse_xhtml, spine_item_paths, text_content

_DATE_FORMATS = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d')


def is_anthology(zf: ZipFile):
    """
    True if this EPUB was bundled by epubmerge (dc:contributor -- verified
    directly against the real fixture, not inferred).
    """
    opf_root, _opf_path = parse_opf(zf)
    if opf_root is None:
        return False
    metadata_el = find_first(opf_root, 'metadata')
    if metadata_el is None:
        return False
    for contributor in find_all(metadata_el, 'contributor'):
        if 'epubmerge' in text_content(contributor).strip().lower():
            return True
    return False


def _is_fic_title_page(path):
    return 'title_page' in path.lower()


def _group_by_fic(paths):
    """Each title-page-shaped spine path starts a new fic group; anything
    before the first one (e.g. an anthology-level cover.xhtml) belongs to
    no fic and is dropped."""
    groups = []
    current = None
    for path in paths:
        if _is_fic_title_page(path):
            current = {'title_page_path': path, 'chapter_paths': []}
            groups.append(current)
        elif current is not None:
            current['chapter_paths'].append(path)
    return groups


def _scrape_title_page(root):
    """Same approach as extractors/fff_titlepage.py's extract_fff_titlepage()
    -- <h3><a href="...">title</a> by ...</h3> for title/storyUrl, then a
    generic scan of every <b>label</b>: value<br/> line, keyed by label
    text rather than a fixed field order (required: the in-progress fic's
    title page has a different field set/order than the completed ones)."""
    result = {}

    h3 = find_first(root, 'h3')
    if h3 is not None:
        a = find_first(h3, 'a')
        if a is not None:
            href = (a.get('href') or '').strip()
            if href:
                result['storyUrl'] = href
            title_text = text_content(a).strip()
            if title_text:
                result['title'] = title_text

    for b in find_all(root, 'b'):
        label = text_content(b).strip()
        if label.endswith(':'):
            label = label[:-1].strip()
        if not label:
            continue
        value = (b.tail or '').strip()
        if value:
            result[label.lower()] = value

    return result


def _parse_int(value):
    if not value:
        return None
    digits = re.sub(r'[^\d]', '', value)
    return int(digits) if digits else None


def _parse_date(value):
    if not value:
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _content_opf_path_for(title_page_path):
    """The fic's own pre-merge content.opf sits as a sibling of its
    OEBPS/ directory -- verified directly: 'N/OEBPS/title_page.xhtml' has
    a sibling 'N/content.opf' in the manifest (inert -- not part of the
    readable spine/manifest chain, media-type="origrootfile/xml")."""
    if 'OEBPS/' not in title_page_path:
        return None
    prefix = title_page_path.rsplit('OEBPS/', 1)[0]
    return prefix + 'content.opf'


def _enrich_from_content_opf(zf, title_page_path, record):
    """Optional cross-check/enrichment, not a hard dependency -- an inert
    epubmerge-specific artifact a different tool (or future epubmerge
    version) might not preserve. Only fills gaps, never overrides the
    title-page scrape."""
    path = _content_opf_path_for(title_page_path)
    if not path:
        return
    try:
        root = ET.fromstring(zf.read(path))
    except (KeyError, ET.ParseError):
        return

    if not record.get('status'):
        for subject in find_all(root, 'subject'):
            text = text_content(subject).strip()
            if text in ('Completed', 'In-Progress'):
                record['status'] = text
                break

    if not record.get('storyUrl'):
        for identifier in find_all(root, 'identifier'):
            text = text_content(identifier).strip()
            if text.startswith('http'):
                record['storyUrl'] = text
                break

    if not record.get('title'):
        title_el = find_first(root, 'title')
        if title_el is not None:
            text = text_content(title_el).strip()
            if text:
                record['title'] = text


def extract_fic_records(zf: ZipFile):
    """
    Returns a list of per-fic dicts (spine order):
    {title, storyUrl, status, numChapters, numWords, datePublished, dateUpdated}
    Sparse -- a field is only present if it was actually found. Returns []
    if this isn't recognized as an anthology at all -- guards on
    is_anthology() itself rather than trusting the caller to check first,
    since a single FFF-generated (non-anthology) fic also has exactly one
    title_page.xhtml and would otherwise produce a spurious "1 fic" report.
    """
    if not is_anthology(zf):
        return []

    opf_root, opf_path = parse_opf(zf)
    if opf_root is None:
        return []

    paths = spine_item_paths(zf, opf_root, opf_path)
    groups = _group_by_fic(paths)

    records = []
    for group in groups:
        title_page_path = group['title_page_path']
        root = parse_xhtml(zf, title_page_path)
        if root is None:
            continue

        scraped = _scrape_title_page(root)
        record = {}
        if scraped.get('title'):
            record['title'] = scraped['title']
        if scraped.get('storyUrl'):
            record['storyUrl'] = scraped['storyUrl']
        if scraped.get('status'):
            record['status'] = scraped['status']
        if scraped.get('chapters') is not None:
            n = _parse_int(scraped.get('chapters'))
            if n is not None:
                record['numChapters'] = n
        if scraped.get('words') is not None:
            n = _parse_int(scraped.get('words'))
            if n is not None:
                record['numWords'] = n
        if scraped.get('published'):
            d = _parse_date(scraped['published'])
            if d is not None:
                record['datePublished'] = d
        if scraped.get('updated'):
            d = _parse_date(scraped['updated'])
            if d is not None:
                record['dateUpdated'] = d

        _enrich_from_content_opf(zf, title_page_path, record)

        if not record.get('numChapters') and group['chapter_paths']:
            record['numChapters'] = len(group['chapter_paths'])

        records.append(record)

    return records


def format_summary(records):
    """
    Human-readable per-fic breakdown, e.g.:
        6/7 fics complete.

        1. In Arduis Fidelis 1 -- Completed (12 ch, 17,673 words)
        ...
        7. In Arduis Fidelis 7 -- In-Progress (110 ch)
    """
    if not records:
        return ''

    complete = sum(1 for r in records if r.get('status') == 'Completed')
    lines = ['%d/%d fics complete.' % (complete, len(records)), '']

    for i, record in enumerate(records, start=1):
        title = record.get('title') or 'Fic %d' % i
        status = record.get('status') or 'Unknown status'
        details = []
        if record.get('numChapters') is not None:
            details.append('%d ch' % record['numChapters'])
        if record.get('numWords') is not None:
            details.append('{:,} words'.format(record['numWords']))
        detail_str = ' (%s)' % ', '.join(details) if details else ''
        lines.append('%d. %s -- %s%s' % (i, title, status, detail_str))

    return '\n'.join(lines)


class AnthologyResult:
    """Duck-typed to match what dialogs.py::PreviewDialog expects from a
    result object (.book_id, .title, .error, .summary_lines()) so that
    dialog can be reused unmodified for this second, independent action --
    it never assumes its results are BookResult instances."""

    def __init__(self, book_id, title, records=None, summary='', existing_column_value=None, error=None):
        self.book_id = book_id
        self.title = title
        self.records = records or []
        self.summary = summary
        self.existing_column_value = existing_column_value
        self.error = error

    def summary_lines(self):
        if self.error:
            return ['Error: %s' % self.error]
        lines = []
        if self.existing_column_value:
            lines.append('(column already has a value)')
            lines.append('')
        lines.extend(self.summary.split('\n'))
        return lines
