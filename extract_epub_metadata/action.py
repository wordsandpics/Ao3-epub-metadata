from zipfile import ZipFile

from calibre.gui2 import error_dialog, info_dialog
from calibre.gui2.actions import InterfaceAction
from qt.core import QMenu

from calibre_plugins.extract_epub_metadata.anthology import (
    AnthologyResult, extract_fic_records, format_summary, is_anthology,
)
from calibre_plugins.extract_epub_metadata.calibre_fields import (
    apply_custom_column_mapping, apply_standard_fields,
    compute_custom_column_values, compute_standard_fields,
)
from calibre_plugins.extract_epub_metadata.common_utils import plugin_icon
from calibre_plugins.extract_epub_metadata.config import (
    KEY_ADD_IDENTIFIER, KEY_ANTHOLOGY_DEST_COLUMN, KEY_ANTHOLOGY_OVERWRITE,
    KEY_ANTHOLOGY_PREVIEW, KEY_ANTHOLOGY_SHOW_CONFIRMATION, KEY_COLUMN_MAPPING,
    KEY_DEST_COLUMN, KEY_MODE1_ENABLED, KEY_MODE2_ENABLED, KEY_MODE2_OVERWRITE,
    KEY_MODE3_ENABLED, KEY_OVERWRITE, KEY_PREVIEW, KEY_SHOW_CONFIRMATION, get_prefs,
)
from calibre_plugins.extract_epub_metadata.dialogs import BookResult, PreviewDialog
from calibre_plugins.extract_epub_metadata.mapping import extract_fields
from calibre_plugins.extract_epub_metadata.serialize import serialize_saved_metadata


class ExtractEpubMetadataAction(InterfaceAction):
    name = 'Extract Epub Metadata'
    action_spec = (
        'Extract Metadata', None,
        'Extract FanFicFare-compatible metadata from the selected EPUB(s) '
        'into the configured Saved Metadata column and/or standard/custom '
        'Calibre fields',
        (),
    )
    action_type = 'current'

    def genesis(self):
        self.qaction.setIcon(plugin_icon())
        self.qaction.triggered.connect(self.run)

        # dropdown arrow (popup_type defaults to MenuButtonPopup) so the
        # settings are reachable without first running an extraction.
        self.menu = QMenu(self.gui)
        self.menu.addAction('Extract Metadata', self.run)
        self.menu.addAction('Extract story status from anthology', self.run_anthology_report)
        self.menu.addAction('Configure…', self.show_configuration)
        self.qaction.setMenu(self.menu)

    def show_configuration(self):
        self.interface_action_base_plugin.do_user_config(self.gui)

    def run(self):
        prefs = get_prefs()
        mode1_on = prefs[KEY_MODE1_ENABLED]
        mode2_on = prefs[KEY_MODE2_ENABLED]
        mode3_on = prefs[KEY_MODE3_ENABLED]
        dest_column = prefs[KEY_DEST_COLUMN]
        column_mapping = prefs[KEY_COLUMN_MAPPING]

        db = self.gui.current_db.new_api
        custom_columns = self.gui.library_view.model().custom_columns

        if not mode1_on and not mode2_on and not mode3_on:
            return error_dialog(
                self.gui, 'Nothing enabled',
                'Enable at least one of "Write to Saved Metadata Column", '
                '"Populate standard Calibre fields", or "Map metadata to '
                'custom columns" in this plugin\'s settings (Preferences → '
                'Plugins) before running it.',
                show=True)

        if mode1_on and (not dest_column or dest_column not in custom_columns
                          or custom_columns[dest_column]['datatype'] != 'comments'):
            return error_dialog(
                self.gui, 'No Saved Metadata column configured',
                'Choose a Long Text ("comments") custom column in this '
                "plugin's settings (Preferences → Plugins) before "
                'running it -- ideally the same column FanFicFare itself '
                'uses for its "Saved Metadata Column" setting. Or disable '
                '"Write to Saved Metadata Column" if you only want '
                'standard/custom-field writes.',
                show=True)

        book_ids = self.gui.library_view.get_selected_ids()
        if not book_ids:
            return error_dialog(
                self.gui, 'No books selected',
                'Select one or more books first.', show=True)

        results = [self._process_book(db, book_id, dest_column, prefs,
                                       mode1_on, mode2_on, mode3_on, column_mapping,
                                       custom_columns)
                   for book_id in book_ids]

        if prefs[KEY_PREVIEW]:
            dialog = PreviewDialog(self.gui, results)
            if dialog.exec() != PreviewDialog.DialogCode.Accepted:
                return
            selected = dialog.selected_results()
        else:
            selected = [r for r in results if not r.error]

        written = self._write_results(db, dest_column, selected, mode1_on, mode2_on, mode3_on)

        if prefs[KEY_SHOW_CONFIRMATION]:
            info_dialog(
                self.gui, 'Extract Epub Metadata',
                'Updated %d of %d selected book(s).' % (written, len(book_ids)),
                show=True)

    def _process_book(self, db, book_id, dest_column, prefs, mode1_on, mode2_on,
                       mode3_on, column_mapping, custom_columns):
        mi = db.get_metadata(book_id)
        title = mi.title or ('Book %s' % book_id)

        if not db.has_format(book_id, 'EPUB'):
            return BookResult(book_id, title, {}, {}, '',
                               error='No EPUB format available for this book.')

        try:
            stream = db.format(book_id, 'EPUB', as_file=True)
            fields, sources = extract_fields(stream)
        except Exception as e:
            return BookResult(book_id, title, {}, {}, '',
                               error='Failed to extract metadata: %s' % e)

        if not fields:
            return BookResult(book_id, title, {}, {}, '',
                               error='No recoverable metadata found in this EPUB.')

        blob = serialize_saved_metadata(fields) if mode1_on else ''

        existing_value = None
        if mode1_on:
            # dest_column is the dict key from custom_columns, which
            # already includes the '#' lookup-name prefix (e.g.
            # '#savedmetadata') -- db.new_api field names take that form
            # directly.
            existing_value = db.field_for(dest_column, book_id, default_value='') or None

        standard_fields = compute_standard_fields(fields) if mode2_on else {}

        custom_column_values = {}
        if mode3_on and column_mapping:
            custom_column_values = compute_custom_column_values(
                fields, column_mapping, custom_columns)

        identifiers = db.field_for('identifiers', book_id, default_value={}) or {}
        identifier_already_set = bool(identifiers.get('url') or identifiers.get('uri'))
        story_url = fields.get('storyUrl') if prefs[KEY_ADD_IDENTIFIER] else None

        return BookResult(
            book_id, title, fields, sources, blob,
            identifier_url=story_url,
            identifier_already_set=identifier_already_set,
            existing_column_value=existing_value,
            standard_fields=standard_fields,
            custom_column_values=custom_column_values,
        )

    def _write_results(self, db, dest_column, results, mode1_on, mode2_on, mode3_on):
        prefs = get_prefs()
        overwrite = prefs[KEY_OVERWRITE]
        mode2_overwrite = prefs[KEY_MODE2_OVERWRITE]
        written = 0
        for result in results:
            if result.error:
                continue

            wrote_something = False

            if mode1_on and (overwrite or not result.existing_column_value):
                db.set_field(dest_column, {result.book_id: result.blob})
                wrote_something = True

            if mode2_on and result.standard_fields:
                apply_standard_fields(db, result.book_id, result.standard_fields, mode2_overwrite)
                wrote_something = True

            if mode3_on and result.custom_column_values:
                apply_custom_column_mapping(db, result.book_id, result.custom_column_values)
                wrote_something = True

            if result.identifier_url and not result.identifier_already_set:
                identifiers = db.field_for(
                    'identifiers', result.book_id, default_value={}) or {}
                identifiers = dict(identifiers)
                # Calibre identifiers can't contain ':' -- FanFicFare
                # decodes 'url'/'uri' by replacing '|' back to ':'
                # (calibre-plugin/fff_plugin.py::get_story_url).
                identifiers['url'] = result.identifier_url.replace(':', '|')
                db.set_field('identifiers', {result.book_id: identifiers})
                wrote_something = True

            if wrote_something:
                written += 1
        return written

    # --- "Extract story status from anthology" -- a second, independent
    # action/pipeline. Does not call extract_fields()/mapping.py at all;
    # see anthology.py's module docstring for why. ---

    def run_anthology_report(self):
        prefs = get_prefs()
        dest_column = prefs[KEY_ANTHOLOGY_DEST_COLUMN]

        db = self.gui.current_db.new_api
        custom_columns = self.gui.library_view.model().custom_columns

        if not dest_column or dest_column not in custom_columns or \
                custom_columns[dest_column]['datatype'] != 'comments':
            return error_dialog(
                self.gui, 'No destination column configured',
                'Choose a Long Text ("comments") custom column on the '
                '"Anthology Status" tab of this plugin\'s settings '
                '(Preferences → Plugins) before running it.',
                show=True)

        book_ids = self.gui.library_view.get_selected_ids()
        if not book_ids:
            return error_dialog(
                self.gui, 'No books selected',
                'Select one or more books first.', show=True)

        results = [self._process_anthology_book(db, book_id, dest_column)
                   for book_id in book_ids]

        if prefs[KEY_ANTHOLOGY_PREVIEW]:
            dialog = PreviewDialog(self.gui, results)
            if dialog.exec() != PreviewDialog.DialogCode.Accepted:
                return
            selected = dialog.selected_results()
        else:
            selected = [r for r in results if not r.error]

        written = self._write_anthology_results(
            db, dest_column, selected, prefs[KEY_ANTHOLOGY_OVERWRITE])

        if prefs[KEY_ANTHOLOGY_SHOW_CONFIRMATION]:
            info_dialog(
                self.gui, 'Extract Epub Metadata',
                'Updated %d of %d selected book(s).' % (written, len(book_ids)),
                show=True)

    def _process_anthology_book(self, db, book_id, dest_column):
        mi = db.get_metadata(book_id)
        title = mi.title or ('Book %s' % book_id)

        if not db.has_format(book_id, 'EPUB'):
            return AnthologyResult(book_id, title,
                                    error='No EPUB format available for this book.')

        try:
            stream = db.format(book_id, 'EPUB', as_file=True)
            with ZipFile(stream) as zf:
                if not is_anthology(zf):
                    return AnthologyResult(
                        book_id, title,
                        error='Not an anthology (no epubmerge marker found) '
                              '-- nothing to summarize.')
                records = extract_fic_records(zf)
        except Exception as e:
            return AnthologyResult(book_id, title,
                                    error='Failed to process anthology: %s' % e)

        if not records:
            return AnthologyResult(book_id, title,
                                    error='No fics recovered from this anthology.')

        existing_value = db.field_for(dest_column, book_id, default_value='') or None

        return AnthologyResult(
            book_id, title, records=records, summary=format_summary(records),
            existing_column_value=existing_value,
        )

    def _write_anthology_results(self, db, dest_column, results, overwrite):
        written = 0
        for result in results:
            if result.error:
                continue
            if result.existing_column_value and not overwrite:
                continue
            db.set_field(dest_column, {result.book_id: result.summary})
            written += 1
        return written
