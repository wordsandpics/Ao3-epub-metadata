"""
Writer for FanFicFare's "Saved Metadata" custom-column format.

IMPORTANT: this targets fanficfare/story.py's Story.dump_html_metadata()
format directly -- the div/class-based HTML below -- because that is what
is genuinely read back by db.field_for()/db.get_custom() and fed into
Story.load_html_metadata(). This was verified two ways against a real
Calibre installation with FanFicFare installed (calibre-debug, scratch
library):
  1. Writing this exact div/class shape through both db.new_api.set_field()
     and the legacy db.set_custom() (the API FFF itself uses) persists it
     completely unchanged -- neither API sanitizes/rewrites comments-column
     HTML on write.
  2. Reading it back and feeding it into the real, installed
     fanficfare.story.Story.load_html_metadata() correctly reconstructs the
     expected metadata dict.

An earlier version of this module targeted a different, simpler-looking
shape (plain <p id="key">value</p> / <ul><li id="key">) copied from a
Saved Metadata column value pasted into chat. That pasted value turned out
to be a *display* artifact: it was copied out of Calibre's GUI comments
editor, whose Qt rich-text widget re-serializes HTML into its own
simplified form when you view or copy from it -- it does not reflect what
is actually stored in the database. Feeding that shape into the real
load_html_metadata() parses to nothing (confirmed empirically). Lesson:
prefer db.field_for() output over anything copied through a GUI editor
when verifying an on-disk format.

Format, per key in self.metadata (sorted alphabetically), skipping keys
starting with `calibre_` and `output_css`:
    <p><span class='label'>{label}</span>: <div class='{classes}' id='{key}'>{value}</div><p>
- plain string  -> classes='metadata',          value verbatim (may itself be HTML)
- datetime/date -> classes='metadata datetime',  value = v.isoformat()
- list          -> classes='metadata list',      value = <ul>\\n<li>a</li>\\n<li>b</li>\\n</ul>
- int           -> classes='metadata int',       value = raw int (also used for True/False)

Read back by fanficfare.story.Story.load_html_metadata(): BeautifulSoup +
html5lib, `soup.find_all('div', 'metadata')`, branching on the `class`
list, keyed by the `id` attribute.
"""
import datetime
from xml.sax.saxutils import escape as _xml_escape

# Fields whose value is already-safe inline HTML (e.g. authorHTML has an
# <a href=...> anchor) and must not be re-escaped.
RAW_HTML_KEYS = frozenset({'authorHTML', 'titleHTML', 'seriesHTML'})

# Human-readable labels for keys we know we may emit. Cosmetic only --
# load_html_metadata() parses by `id`, not by this text. Anything not
# listed here falls back to _default_label().
LABELS = {
    'title': 'Title',
    'author': 'Author',
    'authorId': 'Author ID',
    'authorUrl': 'Author URL',
    'authorHTML': 'Authorhtml',
    'byline': 'Byline',
    'storyId': 'Story ID',
    'storyUrl': 'Story URL',
    'sectionUrl': 'Story URL Section',
    'site': 'Publisher',
    'siteabbrev': 'Site Abbrev',
    'publisher': 'Publisher',
    'description': 'Summary',
    'rating': 'Rating',
    'warnings': 'Warnings',
    'fandoms': 'Fandoms',
    'ships': 'Relationships',
    'characters': 'Characters',
    'freeformtags': 'Freeform Tags',
    'ao3categories': 'AO3 Categories',
    'language': 'Language',
    'langcode': 'Langcode',
    'numWords': 'Words',
    'numChapters': 'Chapters',
    'chapterslashtotal': 'Chapters/Total Chapters',
    'status': 'Status',
    'datePublished': 'Published',
    'dateUpdated': 'Updated',
    'dateCreated': 'Packaged',
    'formatname': 'File Format',
    'formatext': 'File Extension',
}


def _default_label(key):
    # Best-effort fallback for keys without a configured label above --
    # matches FFF's own inconsistent auto-generated labels closely enough
    # (cosmetic only, not parsed).
    return key[:1].upper() + key[1:]


def _escape(value):
    return _xml_escape(str(value))


def serialize_saved_metadata(fields):
    """
    fields: dict[str, value] where value is one of:
      - str (scalar)
      - int (scalar, rendered with the 'int' class)
      - datetime.date / datetime.datetime (rendered as .isoformat(), 'datetime' class)
      - list/tuple of str (rendered as a nested <ul>, 'list' class; empty lists skipped)
    Keys in RAW_HTML_KEYS are emitted verbatim (already-safe inline HTML),
    everything else is XML-escaped.

    Returns the HTML fragment to write into the Saved Metadata column,
    matching fanficfare/story.py's Story.dump_html_metadata() output.
    """
    blocks = []
    for key in sorted(fields.keys()):
        value = fields[key]
        if value in (None, '', [], ()):
            continue
        label = LABELS.get(key, _default_label(key))

        if isinstance(value, (datetime.date, datetime.datetime)):
            classes = 'metadata datetime'
            val_html = value.isoformat()
        elif isinstance(value, (list, tuple)):
            items = [v for v in value if v not in (None, '')]
            if not items:
                continue
            classes = 'metadata list'
            li_items = '\n'.join(
                '<li>{text}</li>'.format(text=item if key in RAW_HTML_KEYS else _escape(item))
                for item in items)
            val_html = '<ul>\n{items}\n</ul>'.format(items=li_items)
        elif isinstance(value, bool):
            classes = 'metadata int'
            val_html = str(value)
        elif isinstance(value, int):
            classes = 'metadata int'
            val_html = str(value)
        else:
            classes = 'metadata'
            val_html = value if key in RAW_HTML_KEYS else _escape(value)

        blocks.append(
            "<p><span class='label'>{label}</span>: "
            "<div class='{classes}' id='{key}'>{val}</div><p>".format(
                label=_escape(label), classes=classes, key=key, val=val_html))

    return '\n'.join(blocks)
