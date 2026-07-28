"""
Tier 2: FanFicFare-generated title page (OEBPS/title_page.xhtml, or
similar), per fanficfare/writers/writer_epub.py's EPUB_TITLE_PAGE_START
template:

    <body class="fff_titlepage">
    <h3><a href="{storyUrl}">{title}</a> by {authorHTML}</h3>
    <div>
    <b>{label}:</b> {value}<br />
    ...

The <h3> link reliably gives the canonical story URL + title. The
<b>Label:</b> value<br/> lines have no `id` attribute (unlike the Saved
Metadata column format), so they're matched by label text -- best-effort,
using FFF's default English labels. personal.ini label customization is
out of scope for v1.

Also handles a plainer variant seen in the wild (no `<b>` tags at all,
one `<p>Label: value</p>` per line instead) -- confirmed against a real
fixture (tests/fixtures/sigh_no_more.epub) where every single field past
title/author/storyUrl was silently dropped because this shape wasn't
recognized as a title page at all (filename has no underscore) and,
even once detected, has zero `<b>` tags for the existing scan to find.

Also recognizes fichub.net's own front-matter filename
(OEBPS/introduction.xhtml, no <h3>/<b> at all -- confirmed against
tests/fixtures/hunted.epub, a fanfiction.net story downloaded via
fichub.net) -- same <p>Label: value</p> shape, scraped the same way.
"""
import re

from ._epubxml import find_all, find_first, parse_opf, parse_xhtml, spine_item_paths, text_content

# "Label: value" as the entire text of a <p>, label kept short so this
# doesn't misfire on ordinary prose (e.g. a summary paragraph) that
# happens to contain a colon.
_PARA_LABEL_RE = re.compile(r'^([A-Za-z][\w \-/]{0,30}):\s*(.+)$', re.DOTALL)


def _is_titlepage(root, path):
    body = find_first(root, 'body')
    cls = (body.get('class') or '') if body is not None else ''
    lowered = path.lower()
    return ('fff_titlepage' in cls.split() or 'title_page' in lowered
            or 'titlepage' in lowered or 'introduction' in lowered)


def extract_fff_titlepage(zf):
    opf_root, opf_path = parse_opf(zf)
    if opf_root is None:
        return None

    for path in spine_item_paths(zf, opf_root, opf_path):
        root = parse_xhtml(zf, path)
        if root is None or not _is_titlepage(root, path):
            continue

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

        # <b>Label:</b> value<br/> -- value is captured in the <b> tag's
        # .tail text (the text immediately following the closing </b>).
        entries = {}
        for b in find_all(root, 'b'):
            label = text_content(b).strip()
            if label.endswith(':'):
                label = label[:-1].strip()
            if not label:
                continue
            value = (b.tail or '').strip()
            if value:
                entries[label] = value

        # Plainer <p>Label: value</p> variant -- only fills gaps, in case
        # a page mixes both styles (unseen in practice, but cheap to be
        # tolerant of).
        for p in find_all(root, 'p'):
            text = text_content(p).strip()
            m = _PARA_LABEL_RE.match(text)
            if not m:
                continue
            label, value = m.group(1).strip(), m.group(2).strip()
            if label and value:
                entries.setdefault(label, value)

        if entries:
            result['label_entries'] = entries

        return result if result else None

    return None
