"""
Small, dependency-free (stdlib-only) helpers for reading EPUB structure and
XHTML content. EPUB content documents are required to be well-formed XML, so
xml.etree.ElementTree is sufficient -- this avoids depending on bs4/lxml,
neither of which Calibre guarantees is importable from plugin code (FFF
vendors its own copy rather than relying on one being present).

Malformed real-world files are handled by returning None/empty from the
parsing helpers rather than raising -- callers degrade to the next
extraction tier instead of crashing the whole pipeline over one bad file.
"""
import posixpath
import xml.etree.ElementTree as ET
from zipfile import ZipFile

OPF_NS = 'http://www.idpf.org/2007/opf'


def local_name(tag):
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def find_all(elem, name):
    """Yield descendant elements whose local tag name matches `name`, namespace-agnostic."""
    for e in elem.iter():
        if local_name(e.tag) == name:
            yield e


def find_first(elem, name):
    for e in find_all(elem, name):
        return e
    return None


def text_content(elem):
    """Concatenate all text within elem, ignoring tag markup (like .get_text())."""
    return ''.join(elem.itertext())


def get_opf_path(zf: ZipFile):
    try:
        container = zf.read('META-INF/container.xml')
        root = ET.fromstring(container)
    except (KeyError, ET.ParseError):
        return None
    rootfile = find_first(root, 'rootfile')
    if rootfile is None:
        return None
    return rootfile.get('full-path')


def parse_opf(zf: ZipFile):
    """Returns (opf_root, opf_path) or (None, None) if unreadable."""
    opf_path = get_opf_path(zf)
    if not opf_path:
        return None, None
    try:
        data = zf.read(opf_path)
        root = ET.fromstring(data)
    except (KeyError, ET.ParseError):
        return None, None
    return root, opf_path


def spine_item_paths(zf: ZipFile, opf_root, opf_path):
    """Content-document hrefs (resolved relative to the OPF) in spine order."""
    if opf_root is None or not opf_path:
        return []
    base = posixpath.dirname(opf_path)
    manifest = {}
    manifest_el = find_first(opf_root, 'manifest')
    if manifest_el is not None:
        for item in find_all(manifest_el, 'item'):
            item_id = item.get('id')
            href = item.get('href')
            if item_id and href:
                manifest[item_id] = href
    spine_el = find_first(opf_root, 'spine')
    paths = []
    if spine_el is not None:
        for itemref in find_all(spine_el, 'itemref'):
            href = manifest.get(itemref.get('idref'))
            if href:
                resolved = posixpath.normpath(posixpath.join(base, href)) if base else href
                paths.append(resolved)
    return paths


def parse_xhtml(zf: ZipFile, path):
    try:
        data = zf.read(path)
    except KeyError:
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None
