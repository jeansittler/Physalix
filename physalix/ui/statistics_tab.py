"""Statistiques mises à jour depuis une grandeur et un intervalle du tableur."""

import csv
import io

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QHeaderView, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QWidget,
)

from physalix.statistics import METRICS, describe
from physalix.spreadsheet import column_label
from physalix.ui.components import label, role, workspace_layout


class StatisticsTab(QWidget):
    def __init__(self, data_tab):
        super().__init__()
        self.data_tab, self.model = data_tab, data_tab.model
        self.results = None
        layout = workspace_layout(self, 760, 520)
        layout.addWidget(label("Statistiques d'une grandeur"))
        row = QHBoxLayout()
        caption = QLabel("Grandeur")
        self.quantity = QComboBox()
        self.quantity.setMinimumContentsLength(18)
        self.quantity.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        caption.setBuddy(self.quantity)
        row.addWidget(caption)
        row.addWidget(self.quantity, 1)
        self.use_selection = QPushButton("Utiliser la sélection du tableur")
        self.use_selection.clicked.connect(self.from_selection)
        row.addWidget(self.use_selection)
        layout.addLayout(row)

        interval = QHBoxLayout()
        self.all_rows = QCheckBox("Toutes les lignes")
        self.all_rows.setChecked(True)
        interval.addWidget(self.all_rows)
        self.first, self.last = QSpinBox(), QSpinBox()
        self.first.setAccessibleName("Première ligne de mesure")
        self.last.setAccessibleName("Dernière ligne de mesure")
        for title, control in (("De la ligne", self.first), ("à", self.last)):
            caption = QLabel(title)
            caption.setBuddy(control)
            interval.addWidget(caption)
            interval.addWidget(control)
        interval.addStretch()
        self.copy_button = QPushButton("Copier les résultats")
        self.copy_button.clicked.connect(self.copy_results)
        interval.addWidget(self.copy_button)
        layout.addLayout(interval)

        self.summary = label("", "muted")
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Indicateur", "Valeur", "Unité", "Définition"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(220)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((245, 150, 80, 320)):
            self.table.setColumnWidth(column, width)
        self.table.verticalHeader().setDefaultSectionSize(32)
        layout.addWidget(self.table, 1)
        layout.addWidget(label(
            "Les cellules vides et les erreurs sont exclues, jamais remplacées par zéro. "
            "Les résultats suivent automatiquement les modifications du tableur.", "muted"))
        layout.addWidget(label(
            "Quartiles : rangs arrondis à l'entier supérieur, sans interpolation. "
            "L'incertitude-type A suppose des mesures répétées indépendantes d'une même grandeur ; "
            "elle n'inclut pas les autres sources d'incertitude.", "muted"))

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.sync)
        for signal in (self.model.dataChanged, self.model.rowsInserted, self.model.columnsInserted, self.model.modelReset):
            signal.connect(lambda *args: self.timer.start(0))
        self.model.columnsRemoved.connect(self.columns_removed)
        self.quantity.currentIndexChanged.connect(self.calculate)
        self.all_rows.toggled.connect(self.calculate)
        self.first.valueChanged.connect(self.calculate)
        self.last.valueChanged.connect(self.calculate)
        self.sync()

    def columns_removed(self, parent, first, last):
        selected = self.quantity.currentData()
        self.quantity.blockSignals(True)
        if selected is not None:
            self.quantity.setItemData(self.quantity.currentIndex(),
                                      -1 if first <= selected <= last else selected - (last - first + 1 if selected > last else 0))
        self.quantity.blockSignals(False)
        self.timer.start(0)

    def sync(self):
        column = self.quantity.currentData()
        initial = self.quantity.count() == 0
        self.quantity.blockSignals(True)
        self.quantity.clear()
        for c, name in enumerate(self.model.names):
            unit = self.model.units[c]
            title = f"{column_label(c)} · {name or 'Grandeur sans nom'}" + (f" ({unit})" if unit else "")
            self.quantity.addItem(title, c)
        self.quantity.setCurrentIndex(0 if initial and self.quantity.count() else self.quantity.findData(column))
        self.quantity.blockSignals(False)
        for control in (self.first, self.last):
            control.blockSignals(True)
            control.setRange(1, max(1, len(self.model.rows)))
            control.blockSignals(False)
        if self.all_rows.isChecked():
            self.last.blockSignals(True)
            self.last.setValue(max(1, len(self.model.rows)))
            self.last.blockSignals(False)
        self.calculate()

    def calculate(self, *args):
        self.results = None
        self.table.setRowCount(0)
        self.copy_button.setEnabled(False)
        self.first.setEnabled(not self.all_rows.isChecked())
        self.last.setEnabled(not self.all_rows.isChecked())
        if self.all_rows.isChecked():
            for control, value in ((self.first, 1), (self.last, max(1, len(self.model.rows)))):
                control.blockSignals(True)
                control.setValue(value)
                control.blockSignals(False)
        column = self.quantity.currentData()
        if column is None or not 0 <= column < self.model.columnCount():
            self.summary.setText("Choisissez une grandeur dans la liste. Ajoutez des données dans le tableur si nécessaire.")
            return
        first, last = (1, len(self.model.rows)) if self.all_rows.isChecked() else (self.first.value(), self.last.value())
        try:
            results, blanks, invalid, overflow = describe(self.model.rows, column, first, last)
        except ValueError as error:
            self.summary.setText(str(error))
            return
        self.results = results
        self.summary.setText(f"Lignes {first} à {last} incluses · {results['count']} valeur(s) retenue(s) · "
                             f"{blanks} cellule(s) vide(s) · {invalid} valeur(s) invalide(s) ou en erreur.")
        unit = self.model.units[column]
        if unit == "Sans unité":
            unit = ""
        self.table.setRowCount(len(METRICS))
        for row, (key, title, power, definition, minimum) in enumerate(METRICS):
            value = results[key]
            reason = "Hors plage numérique" if key in overflow else f"Au moins {minimum} valeur(s) nécessaire(s)."
            rendered = format(value, ".12g").replace(".", ",") if value is not None else "—"
            displayed_unit = (f"({unit})²" if power == 2 else unit) if power and unit else ""
            for column_index, text in enumerate((title, rendered, displayed_unit, definition)):
                item = QTableWidgetItem(text)
                item.setToolTip(reason if value is None else definition)
                if column_index == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column_index, item)
        self.copy_button.setEnabled(results['count'] > 0)

    def from_selection(self):
        indexes = [i for i in self.data_tab.table.selectedIndexes() if i.row() >= self.model.first_data_row]
        columns = {i.column() for i in indexes}
        rows = {i.row() for i in indexes}
        if len(columns) != 1 or not rows or len(rows) != max(rows) - min(rows) + 1:
            self.results = None
            self.table.setRowCount(0)
            self.copy_button.setEnabled(False)
            self.summary.setText("Sélectionnez une plage continue de mesures dans une seule colonne du tableur, puis réessayez.")
            return
        self.sync()
        self.quantity.setCurrentIndex(self.quantity.findData(next(iter(columns))))
        self.all_rows.setChecked(False)
        self.first.setValue(min(rows) - self.model.first_data_row + 1)
        self.last.setValue(max(rows) - self.model.first_data_row + 1)
        self.calculate()

    def copy_results(self):
        if self.results is None or not self.results['count']:
            return
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow(["Grandeur", self.quantity.currentText()])
        writer.writerow([self.summary.text()])
        writer.writerow(["Indicateur", "Valeur", "Unité", "Définition"])
        for row in range(self.table.rowCount()):
            writer.writerow([self.table.item(row, c).text() for c in range(4)])
        QApplication.clipboard().setText(output.getvalue())
