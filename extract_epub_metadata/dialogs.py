from qt.core import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
    QScrollArea, QSplitter, Qt, QVBoxLayout, QWidget,
)

from calibre_plugins.extract_epub_metadata.calibre_fields import (
    ALL_METADATA_KEYS, compatible_columns_for_key, field_help, field_label,
)


def _format_field_dict(fields, sources=None):
    lines = []
    for key in sorted(fields):
        value = fields[key]
        if isinstance(value, list):
            value = '; '.join(str(v) for v in value)
        if sources is not None:
            lines.append('  %s [%s]: %s' % (key, sources.get(key, 'derived'), value))
        else:
            lines.append('  %s: %s' % (key, value))
    return lines


class BookResult:
    """One book's outcome from the extraction/mapping/serialization pipeline.
    `blob` and `standard_fields` are only populated for modes that are
    actually enabled for this run (empty/falsy otherwise), so
    summary_lines() only shows sections for what will actually happen."""

    def __init__(self, book_id, title, fields, sources, blob,
                 identifier_url=None, identifier_already_set=False,
                 existing_column_value=None, standard_fields=None,
                 custom_column_values=None, error=None):
        self.book_id = book_id
        self.title = title
        self.fields = fields
        self.sources = sources
        self.blob = blob
        self.identifier_url = identifier_url
        self.identifier_already_set = identifier_already_set
        self.existing_column_value = existing_column_value
        self.standard_fields = standard_fields or {}
        self.custom_column_values = custom_column_values or {}
        self.error = error

    def summary_lines(self):
        if self.error:
            return ['Error: %s' % self.error]
        lines = []
        if self.identifier_url:
            note = ' (already set, not changed)' if self.identifier_already_set else ' (will be added)'
            lines.append('Story URL identifier: %s%s' % (self.identifier_url, note))
        else:
            lines.append('Story URL identifier: not recovered -- FanFicFare '
                          'may not be able to pick an adapter for this book.')

        if self.blob:
            lines.append('')
            lines.append('=== Saved Metadata Column ===')
            if self.existing_column_value:
                lines.append('(already has a value)')
            lines.append('Recovered fields (source tier in brackets):')
            lines.extend(_format_field_dict(self.fields, self.sources))

        if self.standard_fields:
            lines.append('')
            lines.append('=== Standard Calibre Fields ===')
            lines.extend(_format_field_dict(self.standard_fields))

        if self.custom_column_values:
            lines.append('')
            lines.append('=== Custom Column Mapping ===')
            lines.extend(_format_field_dict(self.custom_column_values))

        return lines


class PreviewDialog(QDialog):
    """Summary of recovered metadata for one or more books, with a
    checkbox per book to include/exclude it from the write, shown before
    anything is actually written."""

    def __init__(self, gui, results):
        QDialog.__init__(self, gui)
        self.setWindowTitle('Extract Epub Metadata -- Preview')
        self.resize(760, 480)
        self.results = results

        layout = QVBoxLayout(self)

        intro = QLabel('Review extracted metadata. Uncheck any book to skip it.')
        intro.setWordWrap(True)
        layout.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        layout.addWidget(splitter, 1)

        self.list_widget = QListWidget(splitter)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for result in results:
            item = QListWidgetItem(result.title or ('Book %s' % result.book_id))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked if result.error else Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, result)
            if result.error:
                item.setToolTip(result.error)
            self.list_widget.addItem(item)
        self.list_widget.currentItemChanged.connect(self._show_details)

        self.details = QPlainTextEdit(splitter)
        self.details.setReadOnly(True)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Write Selected')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)

    def _show_details(self, current, _previous):
        if current is None:
            self.details.setPlainText('')
            return
        result = current.data(Qt.ItemDataRole.UserRole)
        self.details.setPlainText('\n'.join(result.summary_lines()))

    def selected_results(self):
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))
        return selected


class ColumnMappingDialog(QDialog):
    """Mode 3 config: one row per recoverable metadata field (as a static
    label, with a tooltip explaining it), each with a dropdown of the
    custom columns compatible with that field
    (calibre_fields.py::compatible_columns_for_key). Fields with no
    compatible column in this library aren't shown."""

    def __init__(self, gui, custom_columns, current_mapping):
        QDialog.__init__(self, gui)
        self.setWindowTitle('Extract Epub Metadata -- Custom Column Mapping')
        self.resize(600, 420)

        # current_mapping is {column_key: metadata_key} (matches how it's
        # stored/consumed elsewhere) -- invert it once for O(1) lookup of
        # "what column, if any, is this field currently mapped to".
        column_for_key = {v: k for k, v in current_mapping.items()}

        layout = QVBoxLayout(self)

        intro = QLabel(
            'Choose which column each extracted field should be written '
            'to. Empty or not mapped fields will be skipped.')
        intro.setWordWrap(True)
        layout.addWidget(intro)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        form_widget = QWidget(scroll)
        form = QFormLayout(form_widget)

        self.rows = []
        column_names = {key: col['name'] for key, col in custom_columns.items()}
        for metadata_key in sorted(ALL_METADATA_KEYS, key=field_label):
            column_keys = compatible_columns_for_key(metadata_key, custom_columns)
            if not column_keys:
                continue

            combo = QComboBox(form_widget)
            combo.addItem('(not mapped)', '')
            for column_key in sorted(column_keys, key=lambda ck: column_names[ck]):
                combo.addItem(column_names[column_key], column_key)
            idx = combo.findData(column_for_key.get(metadata_key, ''))
            combo.setCurrentIndex(idx if idx >= 0 else 0)

            label = QLabel(field_label(metadata_key) + ':', form_widget)
            help_text = field_help(metadata_key)
            if help_text:
                label.setToolTip(help_text)
                combo.setToolTip(help_text)

            form.addRow(label, combo)
            self.rows.append((metadata_key, combo))

        form_widget.setLayout(form)
        scroll.setWidget(form_widget)
        layout.addWidget(scroll, 1)

        if not self.rows:
            layout.addWidget(QLabel(
                'No custom columns with a supported datatype found. Create '
                'one in Preferences → Add your own columns first.'))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def mapping(self):
        result = {}
        for metadata_key, combo in self.rows:
            column_key = combo.itemData(combo.currentIndex())
            if column_key:
                result[column_key] = metadata_key
        return result
