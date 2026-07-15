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
"""
from ._epubxml import find_all, find_first, parse_opf, parse_xhtml, spine_item_paths, text_content


def _is_titlepage(root, path):
    body = find_first(root, 'body')
    cls = (body.get('class') or '') if body is not None else ''
    return 'fff_titlepage' in cls.split() or 'title_page' in path.lower()


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
        if entries:
            result['label_entries'] = entries

        return result if result else None

    return None
