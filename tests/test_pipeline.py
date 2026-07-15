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

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
sys.path.insert(0, str(TESTS_DIR / 'calibre_stub'))
sys.path.insert(0, str(REPO_ROOT))

from extract_epub_metadata.mapping import extract_fields  # noqa: E402
from extract_epub_metadata.serialize import serialize_saved_metadata  # noqa: E402

EPUB_FIXTURE = TESTS_DIR / 'fixtures' / 'johnlock_a_random_day.epub'
GOLDEN_HTML_FIXTURE = TESTS_DIR / 'fixtures' / 'johnlock_saved_metadata_column.html'

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


if __name__ == '__main__':
    unittest.main()
