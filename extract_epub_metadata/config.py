from calibre.utils.config import JSONConfig
from qt.core import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QVBoxLayout, QWidget,
)

from calibre_plugins.extract_epub_metadata.dialogs import ColumnMappingDialog

# Extra vertical breathing room between the three mode group boxes, so
# they read as clearly separate choices rather than one dense block.
GROUP_SPACING = 14


def _subtext_label(text, parent):
    label = QLabel(text, parent)
    label.setWordWrap(True)
    font = label.font()
    font.setItalic(True)
    label.setFont(font)
    return label


STORE_NAME = 'Options'

KEY_MODE1_ENABLED = 'mode1Enabled'
KEY_DEST_COLUMN = 'destColumn'
KEY_OVERWRITE = 'overwrite'

KEY_MODE2_ENABLED = 'mode2Enabled'
KEY_MODE2_OVERWRITE = 'mode2Overwrite'

KEY_MODE3_ENABLED = 'mode3Enabled'
KEY_COLUMN_MAPPING = 'columnMapping'

KEY_ADD_IDENTIFIER = 'addMissingIdentifier'
KEY_PREVIEW = 'preview'
KEY_SHOW_CONFIRMATION = 'showConfirmation'

# "Extract story status from anthology" -- a separate action/tab, own
# independent prefs (including its own destination column, which can and
# probably should differ from Mode 1's Saved Metadata column).
KEY_ANTHOLOGY_DEST_COLUMN = 'anthologyDestColumn'
KEY_ANTHOLOGY_OVERWRITE = 'anthologyOverwrite'
KEY_ANTHOLOGY_PREVIEW = 'anthologyPreview'
KEY_ANTHOLOGY_SHOW_CONFIRMATION = 'anthologyShowConfirmation'

DEFAULT_STORE_VALUES = {
    # Mode 1 (Saved Metadata column, for FanFicFare's own "Update Calibre
    # Metadata from Saved Metadata Column" action) defaults ON -- it only
    # stages a blob, low-stakes/reversible. Modes 2/3 (direct standard-
    # field / custom-column writes) default OFF -- they mutate the
    # library directly, an existing install shouldn't start doing that
    # just because it picked up a plugin update.
    KEY_MODE1_ENABLED: True,
    KEY_DEST_COLUMN: '',
    KEY_OVERWRITE: False,

    KEY_MODE2_ENABLED: False,
    KEY_MODE2_OVERWRITE: False,

    KEY_MODE3_ENABLED: False,
    KEY_COLUMN_MAPPING: {},

    KEY_ADD_IDENTIFIER: True,
    KEY_PREVIEW: True,
    KEY_SHOW_CONFIRMATION: True,

    KEY_ANTHOLOGY_DEST_COLUMN: '',
    KEY_ANTHOLOGY_OVERWRITE: False,
    KEY_ANTHOLOGY_PREVIEW: True,
    KEY_ANTHOLOGY_SHOW_CONFIRMATION: True,
}

# Always prefix with 'plugins/' so this doesn't collide with a core calibre
# config file.
plugin_prefs = JSONConfig('plugins/Extract Epub Metadata')
plugin_prefs.defaults[STORE_NAME] = DEFAULT_STORE_VALUES


def get_prefs():
    """
    Returns the stored 'Options' dict, backfilled with any keys added to
    DEFAULT_STORE_VALUES since the store was last saved. JSONConfig only
    supplies its `.defaults` when the top-level key ('Options') is missing
    entirely -- it does NOT deep-merge new sub-keys into an already-stored
    dict, so a plain `plugin_prefs[STORE_NAME]` lookup raises KeyError for
    any key added after a user's settings were first saved (confirmed via
    calibre-debug against a real settings file predating mode 2's keys).
    Always read prefs through this function, never `plugin_prefs[STORE_NAME]`
    directly.
    """
    prefs = dict(DEFAULT_STORE_VALUES)
    prefs.update(plugin_prefs[STORE_NAME])
    return prefs


class ConfigWidget(QWidget):
    """Two tabs, kept deliberately separate (not just spaced/divided)
    since they're two unrelated actions sharing one settings dialog:
    "Extraction" (the main Extract Metadata action's 3 modes, unchanged)
    and "Anthology Status" (the "Extract story status from anthology"
    action, added later -- explicitly not crammed into the first tab)."""

    def __init__(self, plugin_action):
        QWidget.__init__(self)
        self.plugin_action = plugin_action
        self.gui = plugin_action.gui

        prefs = get_prefs()
        custom_columns = self.gui.library_view.model().custom_columns

        outer = QVBoxLayout(self)
        self.setLayout(outer)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_extraction_tab(prefs, custom_columns), 'Extraction')
        tabs.addTab(self._build_anthology_tab(prefs, custom_columns), 'Anthology Status')
        outer.addWidget(tabs)

    def _build_extraction_tab(self, prefs, custom_columns):
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        layout.addWidget(self._build_mode1_group(prefs, custom_columns))
        layout.addSpacing(GROUP_SPACING)
        layout.addWidget(self._build_mode2_group(prefs))
        layout.addSpacing(GROUP_SPACING)
        layout.addWidget(self._build_mode3_group(prefs, custom_columns))
        layout.addSpacing(GROUP_SPACING)

        self.add_identifier = QCheckBox(
            'Add missing story-URL identifier', tab)
        self.add_identifier.setToolTip(
            "FanFicFare needs a recognized story URL (Calibre's 'url' or "
            "'uri' identifier) to pick the right site adapter when it reads "
            "back the Saved Metadata column. If checked, a recovered story "
            "URL is written to the book's identifiers when one isn't "
            "already set there -- an existing identifier is never "
            "overwritten. Applies regardless of which modes above are on.")
        self.add_identifier.setChecked(prefs[KEY_ADD_IDENTIFIER])
        layout.addWidget(self.add_identifier)

        self.preview = QCheckBox('Preview before writing', tab)
        self.preview.setToolTip(
            "Show a summary of everything that would be written -- across "
            "whichever modes are enabled above -- for review before "
            "writing anything.")
        self.preview.setChecked(prefs[KEY_PREVIEW])
        layout.addWidget(self.preview)

        self.show_confirmation = QCheckBox('Show confirmation after writing', tab)
        self.show_confirmation.setToolTip(
            "Show a small popup summarizing how many books were updated "
            "after writing finishes. Uncheck to skip it and return "
            "straight to Calibre.")
        self.show_confirmation.setChecked(prefs[KEY_SHOW_CONFIRMATION])
        layout.addWidget(self.show_confirmation)

        layout.addStretch(1)
        return tab

    def _build_anthology_tab(self, prefs, custom_columns):
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        intro = QLabel(
            'Settings for the "Extract story status from anthology" action '
            '(toolbar menu): Recovers the completion status for each '
            'individual fic in a FanFicFare-bundled anthology EPUB, since '
            "the anthology's own aggregate status is manually set and does "
            "not reflect individual stories' status.", tab)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addSpacing(GROUP_SPACING)

        col_row = QHBoxLayout()
        label = QLabel('Destination Column:')
        tooltip = (
            'The custom column to write the per-fic status breakdown into. '
            'Must be a Long Text column. Can be the same column as the '
            'Saved Metadata Column on the Extraction tab, or a different '
            'one.\n(Long Text columns only.)'
        )
        label.setToolTip(tooltip)
        col_row.addWidget(label)

        self.anthology_dest_column = QComboBox(tab)
        self.anthology_dest_column.setToolTip(tooltip)
        self.anthology_dest_column.addItem('', '')
        for key, column in sorted(custom_columns.items()):
            if column['datatype'] == 'comments':
                self.anthology_dest_column.addItem(column['name'], key)
        idx = self.anthology_dest_column.findData(prefs[KEY_ANTHOLOGY_DEST_COLUMN])
        self.anthology_dest_column.setCurrentIndex(idx if idx >= 0 else 0)
        col_row.addWidget(self.anthology_dest_column)
        layout.addLayout(col_row)

        self.anthology_overwrite = QCheckBox('Overwrite existing column value', tab)
        self.anthology_overwrite.setToolTip(
            "If unchecked, books whose destination column already has a "
            "value are skipped rather than overwritten.")
        self.anthology_overwrite.setChecked(prefs[KEY_ANTHOLOGY_OVERWRITE])
        layout.addWidget(self.anthology_overwrite)

        self.anthology_preview = QCheckBox('Preview before writing', tab)
        self.anthology_preview.setToolTip(
            "Show the per-fic breakdown for review before writing anything. "
            "Non-anthology books show up unchecked with an explanatory note.")
        self.anthology_preview.setChecked(prefs[KEY_ANTHOLOGY_PREVIEW])
        layout.addWidget(self.anthology_preview)

        self.anthology_show_confirmation = QCheckBox('Show confirmation after writing', tab)
        self.anthology_show_confirmation.setToolTip(
            "Show a small popup summarizing how many books were updated "
            "after writing finishes. Uncheck to skip it and return "
            "straight to Calibre.")
        self.anthology_show_confirmation.setChecked(prefs[KEY_ANTHOLOGY_SHOW_CONFIRMATION])
        layout.addWidget(self.anthology_show_confirmation)

        layout.addStretch(1)
        return tab

    def _build_mode1_group(self, prefs, custom_columns):
        group = QGroupBox('Save all extracted metadata', self)
        group.setCheckable(True)
        group.setChecked(prefs[KEY_MODE1_ENABLED])
        group.setToolTip(
            "Stages a FanFicFare-format metadata blob in a custom column, "
            "for FanFicFare's own \"Update Calibre Metadata from Saved "
            "Metadata Column\" action to read back later. Does not touch "
            "your library's Title/Tags/etc. directly.")
        self.mode1_group = group

        subtext = _subtext_label(
            '(Raw metadata in one column for FanFicFare processing)', self)

        col_row = QHBoxLayout()
        label = QLabel('Saved Metadata Column:')
        tooltip = (
            'The custom column to write recovered metadata into. Must be a '
            "Long Text column -- point this at the same column FanFicFare's "
            'own "Saved Metadata Column" setting uses, so its "Update '
            'Calibre Metadata from Saved Metadata Column" action can read '
            'it back.\n(Long Text columns only.)'
        )
        label.setToolTip(tooltip)
        col_row.addWidget(label)

        self.dest_column = QComboBox(self)
        self.dest_column.setToolTip(tooltip)
        self.dest_column.addItem('', '')
        for key, column in sorted(custom_columns.items()):
            if column['datatype'] == 'comments':
                self.dest_column.addItem(column['name'], key)
        idx = self.dest_column.findData(prefs[KEY_DEST_COLUMN])
        self.dest_column.setCurrentIndex(idx if idx >= 0 else 0)
        col_row.addWidget(self.dest_column)

        self.overwrite = QCheckBox('Overwrite existing column value', self)
        self.overwrite.setToolTip(
            "If unchecked, books whose Saved Metadata column already has a "
            "value are skipped rather than overwritten.")
        self.overwrite.setChecked(prefs[KEY_OVERWRITE])

        inner = QVBoxLayout()
        inner.addWidget(subtext)
        inner.addLayout(col_row)
        inner.addWidget(self.overwrite)
        group.setLayout(inner)
        return group

    def _build_mode2_group(self, prefs):
        group = QGroupBox('Update standard Calibre metadata', self)
        group.setCheckable(True)
        group.setChecked(prefs[KEY_MODE2_ENABLED])
        group.setToolTip(
            "Writes directly into your library's Title/Author/Tags/Series/"
            "Comments fields, using FanFicFare's own default AO3 field "
            "composition rules -- no need to also run FanFicFare's Update "
            "Calibre Metadata action. This modifies your library directly, "
            "not just a staging column.")
        self.mode2_group = group

        subtext = _subtext_label('(Title, Author, Tags, Series, Comments...)', self)

        self.mode2_overwrite = QCheckBox('Overwrite existing values', self)
        self.mode2_overwrite.setToolTip(
            "If unchecked, a field already populated in Calibre (e.g. an "
            "existing Title or Tags) is left alone rather than overwritten.")
        self.mode2_overwrite.setChecked(prefs[KEY_MODE2_OVERWRITE])

        inner = QVBoxLayout()
        inner.addWidget(subtext)
        inner.addWidget(self.mode2_overwrite)
        group.setLayout(inner)
        return group

    def _build_mode3_group(self, prefs, custom_columns):
        group = QGroupBox('Update custom columns', self)
        group.setCheckable(True)
        group.setChecked(prefs[KEY_MODE3_ENABLED])
        group.setToolTip(
            "Writes specific recovered fields into custom columns you "
            "choose, e.g. a Fandom column or a Words column. This modifies "
            "your library directly, not just a staging column.")
        self.mode3_group = group
        self.column_mapping = dict(prefs[KEY_COLUMN_MAPPING])

        subtext = _subtext_label(
            "(Map extracted data directly to your own columns - useful if "
            "you don't use FanFicFare)", self)

        configure_button = QPushButton('Configure column mapping…', self)
        configure_button.clicked.connect(lambda: self._open_column_mapping(custom_columns))
        self.mode3_summary = QLabel(self)
        self._update_mode3_summary()

        inner = QVBoxLayout()
        inner.addWidget(subtext)
        inner.addWidget(configure_button)
        inner.addWidget(self.mode3_summary)
        group.setLayout(inner)
        return group

    def _open_column_mapping(self, custom_columns):
        dialog = ColumnMappingDialog(self, custom_columns, self.column_mapping)
        if dialog.exec() == ColumnMappingDialog.DialogCode.Accepted:
            self.column_mapping = dialog.mapping()
            self._update_mode3_summary()

    def _update_mode3_summary(self):
        n = len(self.column_mapping)
        self.mode3_summary.setText(
            '%d column%s mapped.' % (n, '' if n == 1 else 's'))

    def save_settings(self):
        prefs = get_prefs()
        prefs[KEY_MODE1_ENABLED] = self.mode1_group.isChecked()
        prefs[KEY_DEST_COLUMN] = self.dest_column.itemData(self.dest_column.currentIndex())
        prefs[KEY_OVERWRITE] = self.overwrite.isChecked()
        prefs[KEY_MODE2_ENABLED] = self.mode2_group.isChecked()
        prefs[KEY_MODE2_OVERWRITE] = self.mode2_overwrite.isChecked()
        prefs[KEY_MODE3_ENABLED] = self.mode3_group.isChecked()
        prefs[KEY_COLUMN_MAPPING] = self.column_mapping
        prefs[KEY_ADD_IDENTIFIER] = self.add_identifier.isChecked()
        prefs[KEY_PREVIEW] = self.preview.isChecked()
        prefs[KEY_SHOW_CONFIRMATION] = self.show_confirmation.isChecked()
        prefs[KEY_ANTHOLOGY_DEST_COLUMN] = self.anthology_dest_column.itemData(
            self.anthology_dest_column.currentIndex())
        prefs[KEY_ANTHOLOGY_OVERWRITE] = self.anthology_overwrite.isChecked()
        prefs[KEY_ANTHOLOGY_PREVIEW] = self.anthology_preview.isChecked()
        prefs[KEY_ANTHOLOGY_SHOW_CONFIRMATION] = self.anthology_show_confirmation.isChecked()
        plugin_prefs[STORE_NAME] = prefs
