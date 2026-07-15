from calibre.gui2 import error_dialog, info_dialog
from calibre.gui2.actions import InterfaceAction

from calibre_plugins.calibre_metadata_recovery.common_utils import plugin_icon
from calibre_plugins.calibre_metadata_recovery.config import (
    KEY_ADD_IDENTIFIER, KEY_DEST_COLUMN, KEY_OVERWRITE, KEY_PREVIEW,
    STORE_NAME, plugin_prefs,
)
from calibre_plugins.calibre_metadata_recovery.dialogs import BookResult, PreviewDialog
from calibre_plugins.calibre_metadata_recovery.mapping import extract_fields
from calibre_plugins.calibre_metadata_recovery.serialize import serialize_saved_metadata


class CalibreMetadataRecoveryAction(InterfaceAction):
    name = 'Calibre Metadata Recovery'
    action_spec = (
        'Recover FFF Metadata', None,
        'Recover FanFicFare-compatible metadata from the selected EPUB(s) '
        'into the configured Saved Metadata column',
        (),
    )
    action_type = 'current'

    def genesis(self):
        self.qaction.setIcon(plugin_icon())
        self.qaction.triggered.connect(self.run)

    def run(self):
        prefs = plugin_prefs[STORE_NAME]
        dest_column = prefs[KEY_DEST_COLUMN]

        db = self.gui.current_db.new_api
        custom_columns = self.gui.library_view.model().custom_columns

        if not dest_column or dest_column not in custom_columns or \
                custom_columns[dest_column]['datatype'] != 'comments':
            return error_dialog(
                self.gui, 'No Saved Metadata column configured',
                'Choose a Long Text ("comments") custom column in this '
                "plugin's settings (Preferences → Plugins) before "
                'running it -- ideally the same column FanFicFare itself '
                'uses for its "Saved Metadata Column" setting.',
                show=True)

        book_ids = self.gui.library_view.get_selected_ids()
        if not book_ids:
            return error_dialog(
                self.gui, 'No books selected',
                'Select one or more books first.', show=True)

        results = [self._process_book(db, book_id, dest_column, prefs)
                   for book_id in book_ids]

        if prefs[KEY_PREVIEW]:
            dialog = PreviewDialog(self.gui, results)
            if dialog.exec() != PreviewDialog.DialogCode.Accepted:
                return
            selected = dialog.selected_results()
        else:
            selected = [r for r in results if not r.error]

        written = self._write_results(db, dest_column, selected)

        info_dialog(
            self.gui, 'Calibre Metadata Recovery',
            'Updated %d of %d selected book(s).' % (written, len(book_ids)),
            show=True)

    def _process_book(self, db, book_id, dest_column, prefs):
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

        blob = serialize_saved_metadata(fields)

        # dest_column is the dict key from custom_columns, which already
        # includes the '#' lookup-name prefix (e.g. '#savedmetadata') --
        # db.new_api field names take that form directly.
        existing_value = db.field_for(dest_column, book_id, default_value='')
        identifiers = db.field_for('identifiers', book_id, default_value={}) or {}
        identifier_already_set = bool(identifiers.get('url') or identifiers.get('uri'))
        story_url = fields.get('storyUrl') if prefs[KEY_ADD_IDENTIFIER] else None

        return BookResult(
            book_id, title, fields, sources, blob,
            identifier_url=story_url,
            identifier_already_set=identifier_already_set,
            existing_column_value=existing_value or None,
        )

    def _write_results(self, db, dest_column, results):
        prefs = plugin_prefs[STORE_NAME]
        overwrite = prefs[KEY_OVERWRITE]
        written = 0
        for result in results:
            if result.error:
                continue
            if result.existing_column_value and not overwrite:
                continue

            db.set_field(dest_column, {result.book_id: result.blob})

            if result.identifier_url and not result.identifier_already_set:
                identifiers = db.field_for(
                    'identifiers', result.book_id, default_value={}) or {}
                identifiers = dict(identifiers)
                # Calibre identifiers can't contain ':' -- FanFicFare
                # decodes 'url'/'uri' by replacing '|' back to ':'
                # (calibre-plugin/fff_plugin.py::get_story_url).
                identifiers['url'] = result.identifier_url.replace(':', '|')
                db.set_field('identifiers', {result.book_id: identifiers})

            written += 1
        return written
