from qt.core import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPlainTextEdit, QSplitter, Qt, QVBoxLayout,
)


class BookResult:
    """One book's outcome from the extraction/mapping/serialization pipeline."""

    def __init__(self, book_id, title, fields, sources, blob,
                 identifier_url=None, identifier_already_set=False,
                 existing_column_value=None, error=None):
        self.book_id = book_id
        self.title = title
        self.fields = fields
        self.sources = sources
        self.blob = blob
        self.identifier_url = identifier_url
        self.identifier_already_set = identifier_already_set
        self.existing_column_value = existing_column_value
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
        if self.existing_column_value:
            lines.append('Saved Metadata column already has a value.')
        lines.append('')
        lines.append('Recovered fields (source tier in brackets):')
        for key in sorted(self.fields):
            value = self.fields[key]
            if isinstance(value, list):
                value = '; '.join(str(v) for v in value)
            source = self.sources.get(key, 'derived')
            lines.append('  %s [%s]: %s' % (key, source, value))
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

        intro = QLabel(
            'Review recovered metadata before writing it into the Saved '
            'Metadata column. Uncheck any book to skip it.')
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
