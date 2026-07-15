from calibre.utils.config import JSONConfig
from qt.core import QCheckBox, QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

STORE_NAME = 'Options'
KEY_DEST_COLUMN = 'destColumn'
KEY_OVERWRITE = 'overwrite'
KEY_PREVIEW = 'preview'
KEY_ADD_IDENTIFIER = 'addMissingIdentifier'

DEFAULT_STORE_VALUES = {
    KEY_DEST_COLUMN: '',
    KEY_OVERWRITE: False,
    KEY_PREVIEW: True,
    KEY_ADD_IDENTIFIER: True,
}

# Always prefix with 'plugins/' so this doesn't collide with a core calibre
# config file.
plugin_prefs = JSONConfig('plugins/Extract Epub Metadata')
plugin_prefs.defaults[STORE_NAME] = DEFAULT_STORE_VALUES


class ConfigWidget(QWidget):
    def __init__(self, plugin_action):
        QWidget.__init__(self)
        self.plugin_action = plugin_action
        self.gui = plugin_action.gui

        prefs = plugin_prefs[STORE_NAME]
        custom_columns = self.gui.library_view.model().custom_columns

        layout = QVBoxLayout(self)
        self.setLayout(layout)

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
        layout.addLayout(col_row)

        self.overwrite = QCheckBox('Overwrite existing column value', self)
        self.overwrite.setToolTip(
            "If unchecked, books whose Saved Metadata column already has a "
            "value are skipped rather than overwritten.")
        self.overwrite.setChecked(prefs[KEY_OVERWRITE])
        layout.addWidget(self.overwrite)

        self.preview = QCheckBox('Preview before writing', self)
        self.preview.setToolTip(
            "Show a summary of recovered fields for review before writing "
            "anything.")
        self.preview.setChecked(prefs[KEY_PREVIEW])
        layout.addWidget(self.preview)

        self.add_identifier = QCheckBox(
            "Add missing story-URL identifier ('url')", self)
        self.add_identifier.setToolTip(
            "FanFicFare needs a recognized story URL (Calibre's 'url' or "
            "'uri' identifier) to pick the right site adapter when it reads "
            "back the Saved Metadata column. If checked, a recovered story "
            "URL is written to the book's identifiers when one isn't "
            "already set there -- an existing identifier is never "
            "overwritten.")
        self.add_identifier.setChecked(prefs[KEY_ADD_IDENTIFIER])
        layout.addWidget(self.add_identifier)

        layout.addStretch(1)

    def save_settings(self):
        prefs = plugin_prefs[STORE_NAME]
        prefs[KEY_DEST_COLUMN] = self.dest_column.itemData(self.dest_column.currentIndex())
        prefs[KEY_OVERWRITE] = self.overwrite.isChecked()
        prefs[KEY_PREVIEW] = self.preview.isChecked()
        prefs[KEY_ADD_IDENTIFIER] = self.add_identifier.isChecked()
        plugin_prefs[STORE_NAME] = prefs
