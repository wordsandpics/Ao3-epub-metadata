"""
Unit tests for the extraction/mapping/serialization pipeline, run against
the real fixtures in tests/fixtures/:
  - johnlock_a_random_day.epub: a real AO3-downloaded (Calibre-converted) EPUB.
  - johnlock_saved_metadata_column.html: the real Saved Metadata column
    value FanFicFare 4.59.5 wrote for that exact fic (pasted by the repo
    owner from their own Calibre library) -- the golden target format.

Run with: python3 -m unittest discover -s tests -v
(no third-party dependencies required; a minimal calibre stub package in
tests/calibre_stub/ lets extract_epub_metadata/__init__.py import outside
a real Calibre installation.)
"""
import datetime
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(TESTS_DIR / 'calibre_stub'))
sys.path.insert(0, str(REPO_ROOT))

from extract_epub_metadata.anthology import (  # noqa: E402
    extract_fic_records, format_summary, is_anthology,
)
from extract_epub_metadata.calibre_fields import (  # noqa: E402
    STATUS_COMPLETE_KEY, compatible_columns_for_key, compute_custom_column_values,
    compute_standard_fields, field_label, permitted_keys_for_datatype,
)
from extract_epub_metadata.mapping import extract_fields  # noqa: E402
from extract_epub_metadata.serialize import serialize_saved_metadata  # noqa: E402

EPUB_FIXTURE = TESTS_DIR / 'fixtures' / 'johnlock_a_random_day.epub'
GOLDEN_HTML_FIXTURE = TESTS_DIR / 'fixtures' / 'johnlock_saved_metadata_column.html'
ANTHOLOGY_FIXTURE = TESTS_DIR / 'fixtures' / 'anthology_in_arduis_fidelis.epub'

# Fields we intend to populate for this fic (see plan's "Field population
# strategy" -- excludes live-fetch-only stats like hits/kudos/comments,
# and internal bookkeeping like adapter_classes/python_version/version).
EXPECTED_POPULATED_KEYS = {
    'ao3categories', 'author', 'authorId', 'authorUrl', 'byline',
    'chapterslashtotal', 'characters', 'dateCreated', 'datePublished',
    'dateUpdated', 'description', 'fandoms', 'formatext', 'formatname',
    'freeformtags', 'langcode', 'language', 'lastupdate', 'numChapters',
    'numWords', 'rating', 'sectionUrl', 'ships', 'site', 'siteabbrev',
    'status', 'storyId', 'storyUrl', 'title', 'warnings',
}


def _local(tag):
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def parse_golden(path):
    """Parse the real Saved-Metadata HTML fixture into {id: value}, where
    value is a str for scalar <p id=...>/<li id=...> (single-item list)
    entries, or a list[str] when the id'd <li> has list siblings."""
    root = ET.fromstring(path.read_text(encoding='utf-8'))
    expected = {}
    for el in root.iter():
        el_id = el.get('id')
        if not el_id:
            continue
        if _local(el.tag) == 'li':
            ul = None
            for parent in root.iter():
                if _local(parent.tag) == 'ul' and el in list(parent):
                    ul = parent
                    break
            items = [''.join(li.itertext()).strip() for li in (list(ul) if ul is not None else [el])]
            expected[el_id] = items  # always a list -- matches our own list-typed output
        else:
            expected[el_id] = ''.join(el.itertext()).strip()
    return expected


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fields, cls.sources = extract_fields(str(EPUB_FIXTURE))
        cls.blob = serialize_saved_metadata(cls.fields)
        cls.golden = parse_golden(GOLDEN_HTML_FIXTURE)

    def test_populates_expected_core_fields(self):
        missing = EXPECTED_POPULATED_KEYS - set(self.fields)
        self.assertFalse(missing, 'missing expected fields: %s' % missing)

    def test_values_match_golden_sample(self):
        # NOTE: the golden fixture is a *display* copy -- pasted from
        # Calibre's GUI comments editor, whose Qt rich-text widget
        # re-serializes HTML on view/copy (div/class -> plain p/ul/li,
        # losing the `class` attribute) rather than the true raw database
        # value. Confirmed via calibre-debug: writing that shape through
        # either db.new_api.set_field() or the legacy db.set_custom() (the
        # API FanFicFare itself uses) round-trips byte-identical -- neither
        # API sanitizes on write -- yet load_html_metadata() finds nothing
        # in it (it only matches `<div class="metadata">`), while feeding
        # it the genuine dump_html_metadata()-shaped output (what
        # serialize.py now produces) parses correctly. So this fixture is
        # only trustworthy for *values*, not HTML structure -- see
        # test_serialized_blob_uses_dump_html_metadata_shape below for the
        # structural check, and test_round_trips_through_fanficfare_
        # load_html_metadata for the authoritative real-parser check.
        skip = {'dateCreated'}  # this run's own timestamp, not comparable
        for key in EXPECTED_POPULATED_KEYS - skip:
            if key not in self.golden:
                continue  # e.g. langcode/language ordering quirks, sectionUrl label vs key, etc.
            actual = self.fields[key]
            expected = self.golden[key]
            if isinstance(actual, (datetime.date, datetime.datetime)):
                actual = actual.isoformat()
            if key in ('numChapters', 'numWords'):
                # actual is a real int now (see serialize.py's docstring on
                # why); golden's display copy shows FFF's read-time
                # comma-formatted string -- compare numerically.
                self.assertEqual(actual, int(str(expected).replace(',', '')),
                                  'field %r mismatch' % key)
            elif isinstance(actual, list):
                self.assertEqual(actual, expected, 'field %r mismatch' % key)
            else:
                self.assertEqual(str(actual), str(expected), 'field %r mismatch' % key)

    def test_serialized_blob_uses_dump_html_metadata_shape(self):
        # Matches fanficfare/story.py's Story.dump_html_metadata() output --
        # verified (via calibre-debug against a real Calibre + FanFicFare
        # install) to be what's actually persisted/retrieved and what
        # load_html_metadata() parses. See the module docstring in
        # serialize.py for how this was confirmed.
        self.assertIn(
            "<div class='metadata list' id='characters'><ul>\n<li>Sherlock Holmes</li>",
            self.blob)
        self.assertIn("<div class='metadata int' id='numChapters'>1</div>", self.blob)
        self.assertIn("<span class='label'>", self.blob)

    def test_omits_unrecoverable_live_stats(self):
        for key in ('hits', 'kudos', 'bookmarks', 'subscribed', 'markedforlater',
                    'python_version', 'version', 'adapter_classes'):
            self.assertNotIn(key, self.fields)

    def test_round_trips_through_fanficfare_load_html_metadata(self):
        # Best-effort: only runs if FanFicFare's own story.py is importable
        # (e.g. extracted from the installed FanFicFare.zip into a local
        # scratch path). Skips cleanly otherwise rather than failing CI
        # environments that don't have it.
        try:
            import fanficfare.story as fff_story  # type: ignore
        except ImportError:
            self.skipTest('fanficfare.story not importable in this environment')

        story = fff_story.Story.__new__(fff_story.Story)
        story.metadata = {}
        story.load_html_metadata(self.blob)

        self.assertEqual(story.metadata.get('storyId'), '88555541')
        self.assertEqual(story.metadata.get('numChapters'), 1)
        self.assertIn('Sherlock Holmes', story.metadata.get('characters', []))
        self.assertIn('Sherlock Holmes/John Watson', story.metadata.get('ships', []))
        self.assertEqual(story.metadata.get('status'), 'Completed')


class DateFieldTypingTest(unittest.TestCase):
    """Regression test: an older fic whose FFF title page renders
    dateCreated ("Packaged") in FFF's space-separated default format
    (%Y-%m-%d %H:%M:%S) rather than the ISO T-separated form. This used to
    leave dateCreated as a raw string, which serialize.py would then emit
    without the 'datetime' class -- load_html_metadata() loads it back as
    plain text, and FanFicFare's own code crashes calling .strftime() on
    it during "Update Calibre Metadata from Saved Metadata Column"
    (observed directly: 'str' object has no attribute 'strftime', see
    tests/fixtures/like_fire_and_water_fff_error_log.txt)."""

    EPUB_FIXTURE = TESTS_DIR / 'fixtures' / 'like_fire_and_water.epub'

    def test_all_date_fields_are_real_datetimes(self):
        fields, sources = extract_fields(str(self.EPUB_FIXTURE))
        for key in ('dateCreated', 'datePublished', 'dateUpdated'):
            if key in fields:
                self.assertIsInstance(
                    fields[key], (datetime.date, datetime.datetime),
                    '%r was left as %r instead of being parsed into a datetime '
                    '(or dropped) -- this is what crashes FFF downstream' % (
                        key, fields[key]))

    def test_serialized_date_fields_carry_the_datetime_class(self):
        fields, _sources = extract_fields(str(self.EPUB_FIXTURE))
        blob = serialize_saved_metadata(fields)
        self.assertIn("<div class='metadata datetime' id='dateCreated'>", blob)
        self.assertNotIn("<div class='metadata' id='dateCreated'>", blob)


class NonAO3FallbackTest(unittest.TestCase):
    """A plain EPUB with no AO3 preface and no FFF title page should fall
    back to tier 1 (OPF) cleanly, without fabricating AO3-shaped fields."""

    EPUB_FIXTURE = TESTS_DIR / 'fixtures' / 'generic_no_markers.epub'

    def test_degrades_to_opf_only(self):
        fields, sources = extract_fields(str(self.EPUB_FIXTURE))

        self.assertEqual(fields.get('title'), 'A Generic Story')
        self.assertEqual(fields.get('author'), ['Jane Author'])
        self.assertEqual(fields.get('description'),
                          'A story with no AO3 or FanFicFare markers at all.')

        for key in ('fandoms', 'ships', 'characters', 'warnings',
                    'freeformtags', 'ao3categories', 'rating', 'status',
                    'numChapters', 'numWords', 'storyId'):
            self.assertNotIn(key, fields, 'unexpected AO3-shaped field %r' % key)

        # no recognized-site link in the body -> no story URL recovered,
        # and therefore no site/siteabbrev/sectionUrl derived from one.
        self.assertNotIn('storyUrl', fields)
        self.assertNotIn('site', fields)


class TitlepageParagraphVariantTest(unittest.TestCase):
    """A title page shaped like <p>Label: value</p> per line (no <b> tags,
    filename 'titlepage.html' with no underscore) was previously invisible
    to tier 2 entirely -- neither recognized as a title page nor scannable
    for entries even if it had been. Regression fixture for that bug."""

    EPUB_FIXTURE = TESTS_DIR / 'fixtures' / 'sigh_no_more.epub'

    def test_recovers_fields_from_paragraph_style_titlepage(self):
        fields, sources = extract_fields(str(self.EPUB_FIXTURE))

        self.assertEqual(fields.get('fandoms'), ['The Pitt (TV)'])
        self.assertEqual(fields.get('ships'), ['Jack Abbot/Michael "Robby" Robinavitch'])
        self.assertEqual(fields.get('freeformtags'), ['PTSD', 'Hurt/Comfort'])
        self.assertEqual(fields.get('ao3categories'), ['M/M'])
        self.assertEqual(fields.get('rating'), 'Mature')
        self.assertEqual(fields.get('status'), 'In-Progress')
        self.assertEqual(fields.get('numWords'), 4066)
        for key in ('fandoms', 'ships', 'freeformtags', 'ao3categories',
                    'rating', 'status', 'numChapters', 'numWords'):
            self.assertEqual(sources.get(key), 'fff_titlepage')

    def test_chapters_slash_notation_recovers_numerator_and_status(self):
        fields, _sources = extract_fields(str(self.EPUB_FIXTURE))

        self.assertEqual(fields.get('numChapters'), 1)
        self.assertEqual(fields.get('chapterslashtotal'), '1/1')

    def test_dates_are_real_datetimes(self):
        fields, _sources = extract_fields(str(self.EPUB_FIXTURE))

        self.assertIsInstance(fields.get('datePublished'), datetime.datetime)
        self.assertIsInstance(fields.get('dateUpdated'), datetime.datetime)


class UnknownChapterTotalTest(unittest.TestCase):
    """"Chapters: 41/?" (an ongoing fic whose final chapter count isn't
    known yet) used to leave numChapters as the raw string '41/?', which
    crashed Calibre outright (ValueError: invalid literal for int()) the
    moment it reached an int-typed custom column via Mode 3. Regression
    fixture for that crash."""

    EPUB_FIXTURE = TESTS_DIR / 'fixtures' / 'crimson_supernova.epub'

    def test_numerator_recovered_as_a_real_int(self):
        fields, _sources = extract_fields(str(self.EPUB_FIXTURE))

        self.assertEqual(fields.get('numChapters'), 41)
        self.assertIsInstance(fields['numChapters'], int)
        self.assertEqual(fields.get('chapterslashtotal'), '41/?')

    def test_status_not_fabricated_from_unknown_total(self):
        # Status still comes through fine here since this title page has
        # its own explicit "Status:" line -- but it must come from that
        # label, not be guessed from the (unknowable) n/? comparison.
        fields, sources = extract_fields(str(self.EPUB_FIXTURE))

        self.assertEqual(fields.get('status'), 'In-Progress')
        self.assertEqual(sources.get('status'), 'fff_titlepage')

    def test_no_non_numeric_string_survives_into_numChapters(self):
        # Direct unit test of the general safety net in
        # mapping.py::_finalize_numerics, independent of any one fixture.
        from extract_epub_metadata.mapping import _finalize_numerics

        fields = {'numChapters': '41/?', 'numWords': '1,234'}
        _finalize_numerics(fields)

        self.assertNotIn('numChapters', fields)
        self.assertEqual(fields['numWords'], 1234)


class ComputeStandardFieldsTest(unittest.TestCase):
    """Mode 2 (direct-to-Calibre-fields): compute_standard_fields() is pure
    and needs no live Calibre, unlike apply_standard_fields()/
    apply_custom_column_mapping() which do db.new_api writes and can only
    be exercised via calibre-debug against a real library (see the plan)."""

    EPUB_FIXTURE = TESTS_DIR / 'fixtures' / 'johnlock_a_random_day.epub'

    @classmethod
    def setUpClass(cls):
        cls.fields, _sources = extract_fields(str(cls.EPUB_FIXTURE))
        cls.computed = compute_standard_fields(cls.fields)

    def test_title_and_authors(self):
        self.assertEqual(self.computed['title'], 'Johnlock—A random day')
        self.assertEqual(self.computed['authors'], ['Sunsoona'])

    def test_tags_composite_matches_fff_defaults(self):
        # FFF's default AO3 Tags composition: fandoms + ships + characters +
        # freeformtags + ao3categories + status -- NOT rating/warnings.
        tags = set(self.computed['tags'])
        self.assertIn('Sherlock (BBC TV 2010)', tags)  # fandoms
        self.assertIn('Sherlock Holmes/John Watson', tags)  # ships
        self.assertIn('Sherlock Holmes', tags)  # characters
        self.assertIn('Johnlock - Freeform', tags)  # freeformtags
        self.assertIn('M/M', tags)  # ao3categories
        self.assertIn('Completed', tags)  # status
        self.assertNotIn('General Audiences', tags)  # rating -- excluded
        self.assertNotIn('Creator Chose Not To Use Archive Warnings', tags)  # warnings -- excluded
        # deduped: no tag should appear twice in the source lists->flattened list
        self.assertEqual(len(self.computed['tags']), len(tags))

    def test_comments_is_raw_not_sanitized(self):
        # sanitize_comments_html() needs a real Calibre import -- deferred
        # to apply_standard_fields() at write time, see calibre_fields.py's
        # module docstring. Here it should just be the plain description.
        self.assertEqual(self.computed['comments'], self.fields['description'])
        self.assertNotIn('<p>', self.computed['comments'])

    def test_no_series_when_not_extracted(self):
        # this fixture's extraction never populates a series01 key.
        self.assertNotIn('series', self.computed)

    def test_pubdate_and_language(self):
        self.assertEqual(self.computed['pubdate'], self.fields['datePublished'])
        self.assertEqual(self.computed['language'], 'English')

    def test_sparse_in_sparse_out(self):
        # no field should be fabricated for a key that was never populated.
        minimal = compute_standard_fields({'title': 'Only A Title'})
        self.assertEqual(minimal, {'title': 'Only A Title'})


class CustomColumnMappingTest(unittest.TestCase):
    """Mode 3: compute_custom_column_values() is pure -- it needs a
    column-metadata dict shaped like db.field_metadata.custom_field_metadata()
    (verified via calibre-debug against a real library, see calibre_fields.py),
    but doesn't need a live `db` itself."""

    @classmethod
    def setUpClass(cls):
        cls.fields, _sources = extract_fields(
            str(TESTS_DIR / 'fixtures' / 'johnlock_a_random_day.epub'))
        cls.columns = {
            '#text_col': {'datatype': 'text', 'is_multiple': False, 'display': {}},
            '#tags_col': {'datatype': 'text', 'is_multiple': True, 'display': {}},
            '#names_col': {'datatype': 'text', 'is_multiple': True,
                           'display': {'is_names': True}},
            '#int_col': {'datatype': 'int', 'is_multiple': False, 'display': {}},
            '#bool_col': {'datatype': 'bool', 'is_multiple': False, 'display': {}},
            '#date_col': {'datatype': 'datetime', 'is_multiple': False, 'display': {}},
            '#enum_col': {'datatype': 'enumeration', 'is_multiple': False,
                          'display': {'enum_values': ['Completed', 'In-Progress']}},
            '#series_col': {'datatype': 'series', 'is_multiple': False, 'display': {}},
        }

    def test_permitted_keys_by_datatype(self):
        self.assertIn('numWords', permitted_keys_for_datatype('int'))
        self.assertNotIn('title', permitted_keys_for_datatype('int'))
        self.assertEqual(permitted_keys_for_datatype('bool'), [STATUS_COMPLETE_KEY])
        self.assertIn('datePublished', permitted_keys_for_datatype('datetime'))
        self.assertIn('fandoms', permitted_keys_for_datatype('text', is_multiple=True))
        # list-kind keys are ALSO offered for non-multiple text columns --
        # _coerce_for_column joins them (', ' or ' & ') rather than
        # rejecting them, so the dropdown shouldn't hide that option.
        self.assertIn('fandoms', permitted_keys_for_datatype('text', is_multiple=False))
        self.assertIn('title', permitted_keys_for_datatype('text', is_multiple=False))

    def test_scalar_text_column(self):
        mapping = {'#text_col': 'rating'}
        values = compute_custom_column_values(self.fields, mapping, self.columns)
        self.assertEqual(values['#text_col'], 'General Audiences')

    def test_multiple_text_column_gets_a_list(self):
        mapping = {'#tags_col': 'characters'}
        values = compute_custom_column_values(self.fields, mapping, self.columns)
        self.assertEqual(values['#tags_col'], self.fields['characters'])

    def test_single_text_column_joins_a_list_source(self):
        mapping = {'#text_col': 'characters'}
        values = compute_custom_column_values(self.fields, mapping, self.columns)
        self.assertEqual(values['#text_col'], ', '.join(self.fields['characters']))

    def test_is_names_column_joins_with_ampersand(self):
        mapping = {'#names_col': 'author'}
        values = compute_custom_column_values(self.fields, mapping, self.columns)
        # single author -- still a list (is_multiple), join logic only
        # applies when the column itself is NOT multiple valued.
        self.assertEqual(values['#names_col'], self.fields['author'])

    def test_int_column(self):
        mapping = {'#int_col': 'numWords'}
        values = compute_custom_column_values(self.fields, mapping, self.columns)
        self.assertEqual(values['#int_col'], self.fields['numWords'])
        self.assertIsInstance(values['#int_col'], int)

    def test_int_column_rejects_non_int_key(self):
        mapping = {'#int_col': 'title'}
        values = compute_custom_column_values(self.fields, mapping, self.columns)
        self.assertNotIn('#int_col', values)

    def test_bool_column_from_status(self):
        mapping = {'#bool_col': STATUS_COMPLETE_KEY}
        values = compute_custom_column_values(self.fields, mapping, self.columns)
        self.assertIs(values['#bool_col'], self.fields['status'] == 'Completed')

    def test_datetime_column(self):
        mapping = {'#date_col': 'datePublished'}
        values = compute_custom_column_values(self.fields, mapping, self.columns)
        self.assertEqual(values['#date_col'], self.fields['datePublished'])

    def test_enumeration_column_accepts_valid_value(self):
        mapping = {'#enum_col': 'status'}
        values = compute_custom_column_values(self.fields, mapping, self.columns)
        self.assertEqual(values['#enum_col'], 'Completed')

    def test_enumeration_column_rejects_value_not_in_enum(self):
        # 'rating' ("General Audiences") isn't one of #enum_col's enum_values.
        mapping = {'#enum_col': 'rating'}
        values = compute_custom_column_values(self.fields, mapping, self.columns)
        self.assertNotIn('#enum_col', values)

    def test_series_column(self):
        fields_with_series = dict(self.fields, series01='My Series [3]')
        mapping = {'#series_col': 'series01'}
        values = compute_custom_column_values(fields_with_series, mapping, self.columns)
        self.assertEqual(values['#series_col'], 'My Series [3]')

    def test_unmapped_columns_produce_nothing(self):
        values = compute_custom_column_values(self.fields, {}, self.columns)
        self.assertEqual(values, {})

    def test_missing_source_key_is_skipped_not_error(self):
        mapping = {'#int_col': 'numWords', '#date_col': 'dateCreated'}
        fields_without_dateCreated = {k: v for k, v in self.fields.items() if k != 'dateCreated'}
        values = compute_custom_column_values(fields_without_dateCreated, mapping, self.columns)
        self.assertIn('#int_col', values)
        self.assertNotIn('#date_col', values)

    def test_compatible_columns_for_key_is_the_reverse_of_permitted_keys(self):
        # numWords (kind='int') should only match the int-typed column.
        self.assertEqual(compatible_columns_for_key('numWords', self.columns), ['#int_col'])
        # datePublished (kind='datetime') should only match the datetime column.
        self.assertEqual(compatible_columns_for_key('datePublished', self.columns), ['#date_col'])
        # the synthetic completed-status key should only match the bool column.
        self.assertEqual(compatible_columns_for_key(STATUS_COMPLETE_KEY, self.columns), ['#bool_col'])
        # a list-kind key should match every text/comments/enumeration
        # column (single or multi-valued -- see _kind_compatible's
        # docstring), but not a series column, which only takes a scalar.
        text_like = compatible_columns_for_key('characters', self.columns)
        for col in ('#text_col', '#tags_col', '#names_col', '#enum_col'):
            self.assertIn(col, text_like)
        self.assertNotIn('#series_col', text_like)
        self.assertNotIn('#int_col', text_like)

    def test_field_label_falls_back_to_raw_key(self):
        self.assertEqual(field_label('numWords'), 'Word Count')
        self.assertEqual(field_label('not_a_real_key'), 'not_a_real_key')


class AnthologyTest(unittest.TestCase):
    """"Extract story status from anthology": a second, independent action
    (see anthology.py's module docstring) -- verified against a real
    epubmerge-produced anthology of 7 fics, 6 Completed + 1 In-Progress."""

    @classmethod
    def setUpClass(cls):
        with ZipFile(ANTHOLOGY_FIXTURE) as zf:
            cls.is_anthology = is_anthology(zf)
            cls.records = extract_fic_records(zf)

    def test_detects_anthology(self):
        self.assertTrue(self.is_anthology)

    def test_recovers_all_seven_fics(self):
        self.assertEqual(len(self.records), 7)

    def test_per_fic_status_and_chapters_match_verified_findings(self):
        # fics 1-6 Completed, fic 7 In-Progress -- matches the research
        # findings recorded in the plan, byte for byte.
        expected = [
            ('Completed', 12), ('Completed', 18), ('Completed', 18),
            ('Completed', 37), ('Completed', 56), ('Completed', 93),
            ('In-Progress', 110),
        ]
        actual = [(r.get('status'), r.get('numChapters')) for r in self.records]
        self.assertEqual(actual, expected)

    def test_only_fic_seven_is_incomplete(self):
        incomplete = [r for r in self.records if r.get('status') != 'Completed']
        self.assertEqual(len(incomplete), 1)
        self.assertEqual(incomplete[0]['title'], 'In Arduis Fidelis 7')

    def test_fic_seven_missing_published_date_handled_gracefully(self):
        # the in-progress fic's title page omits "Published" entirely --
        # confirmed against the real fixture, not assumed. Must not error,
        # and must not fabricate a value.
        fic7 = self.records[6]
        self.assertNotIn('datePublished', fic7)
        self.assertIn('dateUpdated', fic7)

    def test_story_urls_recovered_per_fic(self):
        urls = [r.get('storyUrl') for r in self.records]
        self.assertEqual(urls, [
            'https://archiveofourown.org/works/6194833',
            'https://archiveofourown.org/works/6229315',
            'https://archiveofourown.org/works/6301045',
            'https://archiveofourown.org/works/6407956',
            'https://archiveofourown.org/works/7322257',
            'https://archiveofourown.org/works/9552893',
            'https://archiveofourown.org/works/16979565',
        ])

    def test_format_summary_reports_six_of_seven(self):
        summary = format_summary(self.records)
        self.assertIn('6/7 fics complete.', summary)
        self.assertIn('7. In Arduis Fidelis 7 -- In-Progress', summary)

    def test_non_anthology_epub_is_not_detected(self):
        with ZipFile(EPUB_FIXTURE) as zf:
            self.assertFalse(is_anthology(zf))
            self.assertEqual(extract_fic_records(zf), [])

    def test_format_summary_empty_for_no_records(self):
        self.assertEqual(format_summary([]), '')


if __name__ == '__main__':
    unittest.main()
