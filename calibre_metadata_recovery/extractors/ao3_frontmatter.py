"""
Tier 3: AO3's own native "preface" front matter, verified directly against
a real AO3-downloaded EPUB (see tests/fixtures/johnlock_a_random_day.epub):

    <div id="preface">
      <p class="message">
        <b>{title}</b><br/>
        Posted originally on the <a href="https://archiveofourown.org/">Archive of Our Own</a>
        at <a href="https://archiveofourown.org/works/{storyId}">https://.../works/{storyId}</a>.
      </p>
      <dl class="tags">
        <dt>Rating:</dt><dd><a ...>General Audiences</a></dd>
        <dt>Archive Warning:</dt><dd><a ...>...</a></dd>
        <dt>Category:</dt><dd><a ...>M/M</a></dd>
        <dt>Fandom:</dt><dd><a ...>...</a></dd>
        <dt>Relationships:</dt><dd><a ...>...</a>, <a ...>...</a></dd>
        <dt>Characters:</dt><dd><a ...>...</a>, ...</dd>
        <dt>Additional Tags:</dt><dd><a ...>...</a>, ...</dd>
        <dt>Language:</dt><dd>English</dd>
        <dt>Stats:</dt><dd>Published: 2026-07-14\\nWords: 1,013\\nChapters: 1/1</dd>
      </dl>
    </div>

Field-name mapping to FanFicFare's raw (per-key, pre-composite) vocabulary
is taken directly from fanficfare/adapters/base_otw_adapter.py -- category
and genre are NOT emitted here; FFF composites those at read time from
fandoms/freeformtags/ao3categories via personal.ini's include_in_category/
include_in_genre, so emitting the raw keys keeps that composition working
unmodified.
"""
import re

from ._epubxml import find_all, find_first, parse_opf, parse_xhtml, spine_item_paths, text_content

_DT_TO_KEY = {
    'rating': 'rating',
    'archive warning': 'warnings',
    'category': 'ao3categories',
    'fandom': 'fandoms',
    'relationships': 'ships',
    'characters': 'characters',
    'additional tags': 'freeformtags',
    'language': 'language',
}
_SCALAR_KEYS = {'rating', 'language'}

_WORKS_URL_RE = re.compile(r'/works/(\d+)')
_WORDS_RE = re.compile(r'Words:\s*([\d,]+)')
_CHAPTERS_RE = re.compile(r'Chapters:\s*(\S+)\s*/\s*(\S+)')
_PUBLISHED_RE = re.compile(r'Published:\s*([\d-]+)')
_UPDATED_RE = re.compile(r'Updated:\s*([\d-]+)')
_COMPLETED_RE = re.compile(r'Completed:\s*([\d-]+)')


def _find_preface(root):
    for div in find_all(root, 'div'):
        if div.get('id') == 'preface':
            return div
    return None


def _parse_stats(text, result):
    m = _WORDS_RE.search(text)
    if m:
        result['numWords'] = m.group(1).strip()
    m = _CHAPTERS_RE.search(text)
    if m:
        n, total = m.group(1), m.group(2)
        result['chapterslashtotal'] = '%s/%s' % (n, total)
        if n.isdigit():
            result['numChapters'] = n
        result['status'] = 'Completed' if n == total else 'In-Progress'
    m = _PUBLISHED_RE.search(text)
    if m:
        result['datePublished'] = m.group(1).strip()
        result.setdefault('dateUpdated', m.group(1).strip())
    m = _UPDATED_RE.search(text)
    if m:
        result['dateUpdated'] = m.group(1).strip()
    m = _COMPLETED_RE.search(text)
    if m:
        result['dateUpdated'] = m.group(1).strip()


def extract_ao3_frontmatter(zf):
    opf_root, opf_path = parse_opf(zf)
    if opf_root is None:
        return None

    for path in spine_item_paths(zf, opf_root, opf_path):
        root = parse_xhtml(zf, path)
        if root is None:
            continue
        preface = _find_preface(root)
        if preface is None:
            continue

        result = {}

        message = find_first(preface, 'p')
        if message is not None:
            for a in find_all(message, 'a'):
                href = a.get('href') or ''
                m = _WORKS_URL_RE.search(href)
                if m:
                    result['storyUrl'] = href.strip()
                    result['storyId'] = m.group(1)
                    break
            b = find_first(message, 'b')
            if b is not None:
                title_text = text_content(b).strip()
                if title_text:
                    result['title'] = title_text

        dl = find_first(preface, 'dl')
        if dl is not None:
            dts = list(find_all(dl, 'dt'))
            dds = list(find_all(dl, 'dd'))
            for dt, dd in zip(dts, dds):
                label = text_content(dt).strip()
                if label.endswith(':'):
                    label = label[:-1]
                label = label.strip().lower()

                if label == 'stats':
                    _parse_stats(text_content(dd), result)
                    continue

                key = _DT_TO_KEY.get(label)
                if not key:
                    continue

                tag_links = list(find_all(dd, 'a'))
                if tag_links:
                    values = [text_content(a).strip() for a in tag_links if text_content(a).strip()]
                else:
                    dd_text = text_content(dd).strip()
                    values = [dd_text] if dd_text else []

                if not values:
                    continue
                result[key] = values[0] if key in _SCALAR_KEYS else values

        return result if result else None

    return None
