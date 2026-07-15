"""
Mode 2 ("Populate standard Calibre fields") and Mode 3 ("Map metadata to
custom columns"): write recovered metadata directly into real Calibre
fields, bypassing FanFicFare's own "Update Calibre Metadata from Saved
Metadata Column" action entirely.

This deliberately hardcodes FanFicFare's own *default* AO3 field-
composition rules (plugin-defaults.ini) rather than reimplementing its
general personal.ini/replace_metadata templating engine (~1700 lines
across fanficfare/story.py + fanficfare/configurable.py) -- see the plan's
"Explicit non-goals" section. It will never have FFF's full per-site
customizability; it's a simpler no-round-trip-needed path for the common
case, not a full FFF replacement.

compute_standard_fields() is pure (no Calibre import needed) and unit-
testable the same way as mapping.py/serialize.py -- it returns the *raw*
description under 'comments' rather than sanitizing it, so this module
stays importable outside a real Calibre install (Calibre's own
sanitize_comments_html(), which FFF itself uses, needs a real
`calibre.library` package). apply_standard_fields() and
apply_custom_column_mapping() need a live `db`
(calibre.db.cache.Cache, i.e. self.gui.current_db.new_api), do the
sanitization at write time, and can only be exercised via calibre-debug
against a real library.
"""

# FFF's default include_subject_tags for AO3 (plugin-defaults.ini) is:
# extratags, genre, category, characters, ships, status -- where genre and
# category are themselves composites (include_in_genre: genre,
# freeformtags, ao3categories; include_in_category: category, fandoms).
# Flattened here since we're not reimplementing the composite engine.
# Rating and warnings are intentionally excluded, matching FFF's own
# default (they're not part of include_subject_tags either).
TAG_SOURCE_KEYS = (
    'fandoms', 'ships', 'characters', 'freeformtags', 'ao3categories',
    'status', 'extratags',
)


def compute_standard_fields(fields):
    """
    fields: the dict mapping.py::extract_fields() produces.
    Returns a sparse dict of whatever standard Calibre fields can be
    computed: title, authors, tags, comments (raw, unsanitized), series,
    pubdate, language. Missing source data means a missing key, not a
    fabricated default.

    `series` is passed through as FFF's own "Name [N]" string verbatim --
    Calibre's own db.new_api.set_field('series', ...) parses the trailing
    "[N]" into series/series_index itself (verified via calibre-debug),
    so no parsing is needed here.
    """
    computed = {}

    if fields.get('title'):
        computed['title'] = fields['title']

    author = fields.get('author')
    if author:
        computed['authors'] = author if isinstance(author, list) else [author]

    tags = []
    seen = set()
    for key in TAG_SOURCE_KEYS:
        value = fields.get(key)
        if not value:
            continue
        values = value if isinstance(value, list) else [value]
        for v in values:
            if v and v not in seen:
                seen.add(v)
                tags.append(v)
    if tags:
        computed['tags'] = sorted(tags)

    if fields.get('description'):
        computed['comments'] = fields['description']

    series_raw = fields.get('series01')
    if series_raw:
        computed['series'] = series_raw

    if fields.get('datePublished'):
        computed['pubdate'] = fields['datePublished']

    if fields.get('language'):
        computed['language'] = fields['language']

    return computed


def apply_standard_fields(db, book_id, computed, overwrite):
    """
    Writes `computed` (compute_standard_fields()'s output) into the book's
    real Calibre fields via db.new_api.set_field(). Only touches a field
    if `overwrite` is True, or the book doesn't already have a value there
    -- same overwrite-if-enabled pattern already used for the Saved
    Metadata column and identifiers in action.py. Returns the list of
    Calibre field names actually written, for the preview/summary.
    """
    from calibre.library.comments import sanitize_comments_html

    field_map = {
        'title': 'title',
        'authors': 'authors',
        'tags': 'tags',
        'comments': 'comments',
        'series': 'series',
        'pubdate': 'pubdate',
        'language': 'languages',
    }
    written = []
    for computed_key, calibre_field in field_map.items():
        if computed_key not in computed:
            continue
        if not overwrite and db.field_for(calibre_field, book_id):
            continue
        value = computed[computed_key]
        if computed_key == 'comments':
            value = sanitize_comments_html(value)
        elif calibre_field == 'languages':
            value = [value]
        db.set_field(calibre_field, {book_id: value})
        written.append(calibre_field)
    return written


# --- Mode 3: custom column mapping -----------------------------------------
#
# Every metadata key this plugin can offer for mapping, categorized by
# "kind" -- drives which Calibre custom-column datatypes each key is
# offered for (below) and how its value gets coerced at write time.
# 'text' = scalar string, 'list' = list of strings, 'int' = real int,
# 'datetime' = real datetime.datetime. Deliberately a fixed, hardcoded
# list (like FFF's own permitted_values table) rather than derived from
# whatever a given book's `fields` dict happens to contain, since the
# mapping is configured once, not per-book.
KEY_KINDS = {
    'title': 'text', 'description': 'text', 'rating': 'text', 'language': 'text',
    'langcode': 'text', 'site': 'text', 'siteabbrev': 'text', 'status': 'text',
    'storyId': 'text', 'storyUrl': 'text', 'sectionUrl': 'text',
    'chapterslashtotal': 'text', 'formatname': 'text', 'formatext': 'text',
    'byline': 'text',
    'fandoms': 'list', 'ships': 'list', 'characters': 'list', 'warnings': 'list',
    'freeformtags': 'list', 'ao3categories': 'list', 'author': 'list',
    'authorId': 'list', 'authorUrl': 'list', 'lastupdate': 'list',
    'numWords': 'int', 'numChapters': 'int',
    'datePublished': 'datetime', 'dateUpdated': 'datetime', 'dateCreated': 'datetime',
}

# Synthetic boolean key, not in `fields` directly -- derived from `status`
# at write time (mirrors FFF's status-C/status-I permitted_values entries).
STATUS_COMPLETE_KEY = 'status-C (Completed = checked)'

# Every key the mapping-config UI can offer a row for, KEY_KINDS plus the
# synthetic boolean key -- a stable public list so callers (dialogs.py)
# don't need to reach into KEY_KINDS' internals directly.
ALL_METADATA_KEYS = tuple(KEY_KINDS.keys()) + (STATUS_COMPLETE_KEY,)

# Calibre custom-column datatypes this plugin knows how to write to.
SUPPORTED_DATATYPES = (
    'text', 'comments', 'enumeration', 'series', 'bool', 'int', 'float', 'datetime',
)

# Friendlier display names for the mapping-config UI, since the raw
# KEY_KINDS keys are FanFicFare's own internal vocabulary (some are
# self-explanatory, several are jargon). Falls back to the raw key for
# anything not listed here.
FIELD_LABELS = {
    'title': 'Title',
    'author': 'Author(s)',
    'authorId': 'Author ID',
    'authorUrl': 'Author URL',
    'byline': 'Byline',
    'description': 'Summary',
    'rating': 'Rating',
    'language': 'Language',
    'langcode': 'Language Code',
    'site': 'Site',
    'siteabbrev': 'Site Abbreviation',
    'status': 'Status',
    'storyId': 'Story ID',
    'storyUrl': 'Story URL',
    'sectionUrl': 'Story URL (Section)',
    'chapterslashtotal': 'Chapters (Downloaded/Total)',
    'formatname': 'File Format',
    'formatext': 'File Extension',
    'fandoms': 'Fandom(s)',
    'ships': 'Relationship(s)',
    'characters': 'Characters',
    'warnings': 'Archive Warnings',
    'freeformtags': 'Additional Tags',
    'ao3categories': 'Category',
    'lastupdate': 'Last Update (text)',
    'numWords': 'Word Count',
    'numChapters': 'Chapter Count',
    'datePublished': 'Date Published',
    'dateUpdated': 'Date Updated',
    'dateCreated': 'Date Recovered',
    STATUS_COMPLETE_KEY: 'Completed? (yes/no)',
}

# Explains what each field actually means/where it comes from -- shown as
# a tooltip on the field's label in the mapping dialog, since the
# friendlier names above don't always make that obvious on their own.
FIELD_HELP = {
    'author': 'Author name(s).',
    'authorId': "The site's username for the author.",
    'authorUrl': "Link to the author's profile.",
    'byline': 'Author name(s) as a single line of text.',
    'description': "The story's summary.",
    'rating': 'Content rating, e.g. "Teen And Up Audiences" or "Mature".',
    'language': 'Full language name, e.g. "English".',
    'langcode': 'Short language code, e.g. "en".',
    'site': 'The domain the story was posted on, e.g. "archiveofourown.org".',
    'siteabbrev': 'Short site code FanFicFare uses internally, e.g. "ao3".',
    'status': '"Completed" or "In-Progress".',
    'storyId': "The site's internal ID number for this story.",
    'storyUrl': 'Link to the original story.',
    'sectionUrl': 'Same as Story URL, unless only part of the story was recovered.',
    'chapterslashtotal': 'Chapters recovered vs. total chapters, e.g. "12/12".',
    'fandoms': 'The fandom(s)/canon(s) this story is set in.',
    'ships': 'Relationships/pairings, as tagged on the source site.',
    'warnings': "Archive warnings, e.g. \"Creator Chose Not To Use Archive Warnings\".",
    'freeformtags': "AO3's freeform/additional tags.",
    'ao3categories': 'AO3 category, e.g. "M/M", "F/F", "Gen".',
    'lastupdate': 'Human-readable last-updated text, e.g. "2024/03".',
    'dateCreated': 'When this plugin ran -- not a date from the source site.',
    STATUS_COMPLETE_KEY: 'True if the recovered status is "Completed", false otherwise.',
}


def field_label(metadata_key):
    return FIELD_LABELS.get(metadata_key, metadata_key)


def field_help(metadata_key):
    return FIELD_HELP.get(metadata_key, '')


def _kind_compatible(kind, datatype, is_multiple):
    """
    Shared compatibility rule between a metadata key's `kind`
    (KEY_KINDS-style: 'text'/'list'/'int'/'datetime') and a custom
    column's datatype/is_multiple -- used both to list which metadata
    keys suit a given column (permitted_keys_for_datatype) and, in
    reverse, which columns suit a given key (compatible_columns_for_key).
    List-kind values are offered for non-multiple text/comments/
    enumeration columns too, since _coerce_for_column joins them
    (', ' or ' & ' for "contains names" columns) rather than rejecting them.
    """
    if datatype in ('int', 'float'):
        return kind == 'int'
    if datatype == 'datetime':
        return kind == 'datetime'
    if datatype == 'series':
        return kind == 'text'
    if datatype in ('text', 'comments', 'enumeration'):
        return kind in ('text', 'list')
    return False


def permitted_keys_for_datatype(datatype, is_multiple=False):
    """
    Returns the list of metadata keys (KEY_KINDS keys, plus the synthetic
    STATUS_COMPLETE_KEY where relevant) that make sense to offer for a
    custom column of the given Calibre datatype.
    """
    if datatype == 'bool':
        return [STATUS_COMPLETE_KEY]
    return [k for k, kind in KEY_KINDS.items() if _kind_compatible(kind, datatype, is_multiple)]


def compatible_columns_for_key(metadata_key, custom_columns):
    """
    Reverse of permitted_keys_for_datatype: given a metadata key, which of
    `custom_columns` (a field_metadata-shaped dict, e.g.
    db.field_metadata.custom_field_metadata()) can it be written to?
    """
    if metadata_key == STATUS_COMPLETE_KEY:
        return [key for key, column in custom_columns.items()
                if column['datatype'] == 'bool']
    kind = KEY_KINDS.get(metadata_key)
    if kind is None:
        return []
    return [key for key, column in custom_columns.items()
            if column['datatype'] in SUPPORTED_DATATYPES
            and _kind_compatible(kind, column['datatype'], bool(column.get('is_multiple')))]


def _coerce_for_column(fields, metadata_key, column):
    """
    Returns (value, ok) for writing `metadata_key`'s value from `fields`
    into a column with the given field_metadata dict, coerced to what that
    datatype expects. ok=False means "don't write anything for this book"
    (missing source data, or -- for enumeration columns -- the value isn't
    one of the column's allowed enum_values, which Calibre would otherwise
    silently no-op on anyway; skip it explicitly instead).
    """
    datatype = column['datatype']
    is_multiple = bool(column.get('is_multiple'))
    is_names = bool((column.get('display') or {}).get('is_names'))

    if metadata_key == STATUS_COMPLETE_KEY:
        status = fields.get('status')
        if not status:
            return None, False
        return (status == 'Completed'), True

    value = fields.get(metadata_key)
    if not value:
        return None, False
    kind = KEY_KINDS.get(metadata_key)
    values = value if isinstance(value, list) else [value]

    if datatype in ('int', 'float'):
        if kind != 'int':
            return None, False
        return value, True

    if datatype == 'datetime':
        if kind != 'datetime':
            return None, False
        return value, True

    if datatype == 'series':
        return values[0], True

    if datatype in ('text', 'comments', 'enumeration'):
        if is_multiple:
            return values, True
        joined = (' & ' if is_names else ', ').join(str(v) for v in values)
        if datatype == 'enumeration':
            enum_values = (column.get('display') or {}).get('enum_values') or []
            if joined not in enum_values:
                return None, False
        return joined, True

    return None, False


def compute_custom_column_values(fields, mapping, column_metadata):
    """
    mapping: {column_lookup_key: metadata_key} as configured in
        plugin_prefs (metadata_key may be STATUS_COMPLETE_KEY).
    column_metadata: db.field_metadata.custom_field_metadata() (or an
        equivalent dict), used to look up each column's datatype/
        is_multiple/is_names/enum_values.
    Pure (no db writes) -- returns {column_lookup_key: value} for whatever
    mapped columns have a coercible value for these fields. A column is
    silently omitted (not an error) if its source key is missing/empty/
    incompatible with that column's datatype -- an incomplete mapping is a
    normal state (unlike Mode 1's required destination column). Used both
    to preview what Mode 3 would write and, via apply_custom_column_mapping,
    to actually write it.
    """
    computed = {}
    for column_key, metadata_key in mapping.items():
        column = column_metadata.get(column_key)
        if not column:
            continue
        value, ok = _coerce_for_column(fields, metadata_key, column)
        if ok:
            computed[column_key] = value
    return computed


def apply_custom_column_mapping(db, book_id, computed_values):
    """
    Writes `computed_values` (compute_custom_column_values()'s output) via
    db.new_api.set_field(). Returns the list of column lookup keys written.
    """
    for column_key, value in computed_values.items():
        db.set_field(column_key, {book_id: value})
    return list(computed_values.keys())
