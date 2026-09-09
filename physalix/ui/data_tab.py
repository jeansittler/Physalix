"""Tableau de mesures : une grandeur par colonne, une mesure par ligne."""

import csv
import io
import re
import math
import json

from PySide6.QtCore import QAbstractTableModel, QEvent, QItemSelection, QItemSelectionModel, QMimeData, QModelIndex, Qt, Signal
from PySide6.QtGui import QKeySequence, QRegularExpressionValidator, QColor, QBrush, QPen, QUndoCommand, QUndoStack
from PySide6.QtCore import QRegularExpression
from PySide6.QtWidgets import (
    QAbstractItemDelegate, QAbstractItemView, QApplication, QComboBox, QCompleter, QHeaderView,
    QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QStyle, QStyleOptionViewItem,
    QStyledItemDelegate, QVBoxLayout, QWidget,
)

from physalix.ui.fill_table import FillTableView
from physalix.ui.units import COMMON_UNITS
from physalix.ui.theme import LIGHT
from physalix.ui.components import help_toggle, page_layout, role
from physalix.ui.math_help import math_help_button
from physalix.spreadsheet import CellFormula, CellError, column_label, remove_formula_column, translate_formula


class CellEdit(QUndoCommand):
    def __init__(self, model, values, title):
        super().__init__(title)
        self.model = model
        self.after = values
        self.before = {key: model.data(model.index(*key), Qt.ItemDataRole.EditRole) for key in values}

    def apply(self, values):
        self.model._editing = True
        try:
            for (row, column), text in values.items():
                self.model.setData(self.model.index(row, column), text)
        finally:
            self.model._editing = False
        self.model.recalculate_cells()

    def undo(self):
        self.apply(self.before)

    def redo(self):
        self.apply(self.after)


class MoveColumn(QUndoCommand):
    def __init__(self, table, old, new):
        super().__init__("Déplacer une colonne")
        self.table, self.old, self.new = table, old, new
        self.first = True

    def move(self, source, target):
        header = self.table.horizontalHeader()
        header.blockSignals(True)
        header.moveSection(source, target)
        header.blockSignals(False)

    def undo(self):
        self.move(self.new, self.old)

    def redo(self):
        if self.first:
            self.first = False
        else:
            self.move(self.old, self.new)


class MeasurementsModel(QAbstractTableModel):
    """Conserver les noms et les valeurs, y compris les mesures incomplètes."""

    name_row = 0
    unit_row = 1
    first_data_row = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.names = ["x", "y"]
        self.units = ["", ""]
        self.rows = [["", ""] for _ in range(20)]
        self.calculated_columns = set()
        self.column_dependencies = {}
        self.formulas = {}
        self.formula_errors = {}
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(100)
        self._editing = False
        self._recalculating = False
        self.calculation_engine = None
        self.dataChanged.connect(self.recalculate_cells)
        self.columnsInserted.connect(self.recalculate_cells)
        self.rowsInserted.connect(self.recalculate_cells)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows) + self.first_data_row

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.names)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if index.row() == self.name_row:
                return self.names[index.column()]
            if index.row() == self.unit_row:
                return self.units[index.column()]
            if role == Qt.ItemDataRole.EditRole and (index.row() - self.first_data_row, index.column()) in self.formulas:
                return self.formulas[index.row() - self.first_data_row, index.column()]
            return self.rows[index.row() - self.first_data_row][index.column()]
        key = (index.row() - self.first_data_row, index.column())
        if role == Qt.ItemDataRole.ToolTipRole and key in self.formulas:
            return self.formulas[key] + ("\n" + self.formula_errors[key] if key in self.formula_errors else "")
        if role == Qt.ItemDataRole.ForegroundRole and key in self.formulas:
            return QBrush(QColor("#b42318" if key in self.formula_errors else LIGHT.primary))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignVCenter | (
                Qt.AlignmentFlag.AlignLeft if index.row() < self.first_data_row
                else Qt.AlignmentFlag.AlignRight))
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return f"{column_label(section)} · Grandeur {section + 1}"
            if section == self.name_row:
                return "Grandeur"
            if section == self.unit_row:
                return "Unité"
            return str(section - self.first_data_row + 1)
        return None

    def flags(self, index):
        if index.column() in self.calculated_columns and index.row() >= self.first_data_row:
            return super().flags(index) & ~Qt.ItemFlag.ItemIsEditable
        return super().flags(index) | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        if index.column() in self.calculated_columns and index.row() >= self.first_data_row:
            return False
        text = str(value).strip()
        if index.row() == self.name_row:
            self.names[index.column()] = text
        elif index.row() == self.unit_row:
            self.units[index.column()] = text
        else:
            key = (index.row() - self.first_data_row, index.column())
            if text.startswith("="):
                self.formulas[key] = text
            else:
                self.formulas.pop(key, None)
                self.formula_errors.pop(key, None)
            self.rows[key[0]][key[1]] = text
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, role])
        if text and index.row() == self.rowCount() - 1:
            self.add_row()
        return True

    def edit_cells(self, values, title="Modifier les cellules"):
        values = {key: str(value).strip() for key, value in values.items()
                  if self.flags(self.index(*key)) & Qt.ItemFlag.ItemIsEditable
                  and self.data(self.index(*key), Qt.ItemDataRole.EditRole) != str(value).strip()}
        if values:
            self.undo_stack.push(CellEdit(self, values, title))

    def recalculate_cells(self, *args):
        if self._recalculating or self._editing or not self.formulas:
            return
        self._recalculating = True
        cache, visiting, errors = {}, set(), {}
        engine = self.calculation_engine
        calculated = {item.column: item for item in engine.items} if engine else {}
        def resolve(row, column):
            key = row, column
            if key in cache:
                if isinstance(cache[key], CellError):
                    raise cache[key]
                return cache[key]
            if key in visiting:
                raise CellError("#CYCLE!", "Dépendance circulaire entre cellules ou colonnes calculées.")
            if len(visiting) > 150:
                raise CellError("#LIMITE!", "Chaîne de dépendances trop longue.")
            if not 0 <= column < self.columnCount() or row < 0:
                raise CellError("#REF!", "La colonne ou la ligne référencée n'existe pas.")
            if row >= len(self.rows):
                return 0.0
            visiting.add(key)
            try:
                if key in self.formulas:
                    result = CellFormula(self.formulas[key]).evaluate(resolve)
                elif column in calculated:
                    item = calculated[column]
                    if item.formula:
                        values = [""] * self.columnCount()
                        for ref in set(item.formula.references.values()):
                            values[ref] = str(resolve(row, ref))
                        result = item.formula.evaluate(values)
                    elif 0 < row < len(self.rows) - 1:
                        t0, t1, t2 = [resolve(r, item.axis) for r in (row - 1, row, row + 1)]
                        if not (t0 < t1 < t2 or t0 > t1 > t2):
                            raise ValueError("Intervalle de dérivation invalide.")
                        result = (resolve(row + 1, item.source) - resolve(row - 1, item.source)) / (t2 - t0)
                    else:
                        raise ValueError("Dérivée indisponible à cette extrémité.")
                else:
                    result = float(self.rows[row][column].replace(",", ".") or "0")
                if not math.isfinite(result):
                    raise ValueError("Résultat non fini.")
                cache[key] = result
                return result
            except CellError as error:
                cache[key] = error
                raise
            except ZeroDivisionError:
                error = CellError("#DIV/0!", "Division par zéro.")
                cache[key] = error
                raise error from None
            except (ValueError, TypeError, ArithmeticError, RecursionError) as cause:
                error = CellError("#ERREUR!", str(cause))
                cache[key] = error
                raise error from None
            finally:
                visiting.remove(key)
        resolve.is_blank = lambda r, c: (0 <= c < self.columnCount() and (r, c) not in self.formulas
                                         and c not in calculated and (r >= len(self.rows) or not self.rows[r][c]))
        changed = []
        try:
            for key in self.formulas:
                try:
                    value = format(resolve(*key), ".12g")
                except CellError as error:
                    value, errors[key] = error.code, str(error)
                row, column = key
                if self.rows[row][column] != value or self.formula_errors.get(key) != errors.get(key):
                    self.rows[row][column] = value
                    changed.append(key)
            self.formula_errors = errors
            if changed:
                self.dataChanged.emit(self.index(min(r for r, c in changed) + 2, min(c for r, c in changed)),
                                      self.index(max(r for r, c in changed) + 2, max(c for r, c in changed)), [])
        finally:
            self._recalculating = False

    def add_row(self):
        position = self.rowCount()
        self.beginInsertRows(QModelIndex(), position, position)
        self.rows.append([""] * len(self.names))
        self.endInsertRows()

    def add_quantity(self):
        position = self.columnCount()
        self.beginInsertColumns(QModelIndex(), position, position)
        self.names.append(f"Grandeur {position + 1}")
        self.units.append("")
        for row in self.rows:
            row.append("")
        self.endInsertColumns()

    def quantities_to_remove(self, column):
        if not 0 <= column < self.columnCount():
            return []
        removed = {column}
        while True:
            dependents = {c for c, refs in self.column_dependencies.items() if refs & removed}
            if dependents <= removed:
                return sorted(removed)
            removed.update(dependents)

    def remove_quantity(self, column):
        columns = self.quantities_to_remove(column)
        if columns:
            self.undo_stack.clear()
        for column in reversed(columns):
            self.beginRemoveColumns(QModelIndex(), column, column)
            del self.names[column]
            del self.units[column]
            for row in self.rows:
                del row[column]
            self.calculated_columns = {c - (c > column) for c in self.calculated_columns if c != column}
            self.column_dependencies = {
                c - (c > column): {ref - (ref > column) for ref in refs}
                for c, refs in self.column_dependencies.items() if c != column
            }
            self.formulas = {(r, c - (c > column)): remove_formula_column(text, column)
                             for (r, c), text in self.formulas.items() if c != column}
            self.formula_errors = {}
            self.endRemoveColumns()
        if columns and self.columnCount():
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)
        self.recalculate_cells()
        return bool(columns)


class MeasurementDelegate(QStyledItemDelegate):
    """Accepter les nombres français et valider la saisie avec Entrée."""

    advance = Signal()

    def createEditor(self, parent, option, index):
        if index.row() == index.model().unit_row:
            editor = QComboBox(parent)
            editor.setEditable(True)
            editor.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            editor.addItems(COMMON_UNITS)
            editor.setMaxVisibleItems(12)
            editor.lineEdit().setPlaceholderText("Choisir ou saisir une unité")
            editor.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            editor.completer().setFilterMode(Qt.MatchFlag.MatchContains)
            editor.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseSensitive)
            return editor
        editor = QLineEdit(parent)
        if index.row() >= index.model().first_data_row:
            expression = QRegularExpression(
                r"(?:=[^\n]*|(?:[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)?)"
            )
            editor.setValidator(QRegularExpressionValidator(expression, editor))
        return editor

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            editor.setEditText(index.data(Qt.ItemDataRole.EditRole))
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        value = editor.currentText() if isinstance(editor, QComboBox) else editor.text()
        model.edit_cells({(index.row(), index.column()): value}, "Modifier une cellule")

    def paint(self, painter, option, index):
        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        if index.row() < index.model().first_data_row:
            option.backgroundBrush = QBrush(QColor(LIGHT.secondary))
            option.font.setBold(index.row() == index.model().name_row)
        if index.row() == index.model().unit_row:
            option.text = (index.data() or "Choisir ou saisir…") + "   ▾"
        option.widget.style().drawControl(
            QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.save()
            painter.setPen(QPen(QColor(LIGHT.primary), 2))
            painter.drawRect(option.rect.adjusted(1, 1, -1, -1))
            painter.restore()

    def eventFilter(self, editor, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter,
        ):
            if isinstance(editor, QComboBox) or editor.hasAcceptableInput():
                self.commitData.emit(editor)
                self.closeEditor.emit(editor, QAbstractItemDelegate.EndEditHint.NoHint)
                self.advance.emit()
            return True
        return super().eventFilter(editor, event)


class MeasurementsTable(FillTableView):
    """Déplacer la sélection vers le bas après validation."""

    add_quantity_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        header = self.horizontalHeader()
        header.setSectionsMovable(True)
        header.setFirstSectionMovable(True)
        header.setToolTip("Glissez un en-tête pour déplacer la colonne. Sa lettre et ses références restent attachées à la grandeur.")
        header.sectionMoved.connect(lambda logical, old, new: self.model().undo_stack.push(MoveColumn(self, old, new)))
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.header_context_menu)

    def header_context_menu(self, position):
        header = self.horizontalHeader()
        column = header.logicalIndexAt(position)
        menu = QMenu(self)
        if column >= 0:
            menu.addAction("Supprimer la grandeur…", lambda: self.delete_quantity(column))
            menu.addSeparator()
        menu.addAction("Nouvelle grandeur", self.add_quantity_requested.emit)
        menu.exec(header.viewport().mapToGlobal(position))

    def delete_quantity(self, column):
        model = self.model()
        columns = model.quantities_to_remove(column)
        if not columns:
            return
        message = f"Supprimer « {model.names[column] or f'Grandeur {column + 1}'} » et ses valeurs ?"
        if len(columns) > 1:
            message += "\n\nLes grandeurs calculées qui en dépendent seront aussi supprimées :\n" + "\n".join(
                f"• {model.names[c]}" for c in columns if c != column)
        if QMessageBox.question(self, "Supprimer une grandeur", message,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            model.remove_quantity(column)

    def copy_selection(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        selected = {(index.row(), index.column()) for index in indexes}
        top, bottom = min(r for r, c in selected), max(r for r, c in selected)
        header = self.horizontalHeader()
        left, right = min(header.visualIndex(c) for r, c in selected), max(header.visualIndex(c) for r, c in selected)
        columns = [header.logicalIndex(v) for v in range(left, right + 1)]
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        payload = []
        for row in range(top, bottom + 1):
            writer.writerow([
                self.model().index(row, column).data() if (row, column) in selected else ""
                for column in columns
            ])
            payload.append([[row, column, self.model().index(row, column).data(Qt.ItemDataRole.EditRole)
                             if (row, column) in selected else ""] for column in columns])
        mime = QMimeData()
        mime.setText(output.getvalue())
        mime.setData("application/x-physalix-cells", json.dumps(payload).encode("utf-8"))
        QApplication.clipboard().setMimeData(mime)

    def paste_clipboard(self):
        text = QApplication.clipboard().text()
        if not text:
            return
        model = self.model()
        ranges = list(self.selectionModel().selection())
        header = self.horizontalHeader()
        start = (model.index(min(area.top() for area in ranges),
                             min((index.column() for index in self.selectedIndexes()), key=header.visualIndex))
                 if ranges else self.currentIndex())
        if not start.isValid():
            return
        try:
            # La virgule reste un séparateur décimal, jamais un séparateur de colonnes.
            delimiter = "\t" if "\t" in text or text.lstrip().startswith("=") else ";"
            rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True))
            if not rows:
                return
            width = max(1, max(map(len, rows)))
            rows = [[value.strip() for value in row] + [""] * (width - len(row)) for row in rows]
            first_visual = header.visualIndex(start.column())
            columns = [header.logicalIndex(v) if v < header.count() else model.columnCount() + v - header.count()
                       for v in range(first_visual, first_visual + width)]
            mime = QApplication.clipboard().mimeData()
            if mime.hasFormat("application/x-physalix-cells"):
                try:
                    payload = json.loads(bytes(mime.data("application/x-physalix-cells")))
                    if len(payload) == len(rows) and all(len(row) == width for row in payload):
                        for r, entries in enumerate(payload):
                            for c, (source_row, source_column, value) in enumerate(entries):
                                if isinstance(value, str) and value.startswith("="):
                                    rows[r][c] = translate_formula(value, start.row() + r - source_row, columns[c] - source_column)
                except (ValueError, TypeError, IndexError):
                    pass
            for offset, row in enumerate(rows):
                target_row = start.row() + offset
                for column_offset, value in enumerate(row):
                    column = columns[column_offset]
                    if target_row >= model.first_data_row:
                        if column in model.calculated_columns:
                            raise ValueError("La zone de collage contient une colonne calculée, non modifiable.")
                        if not value.startswith("=") and not re.fullmatch(r"(?:[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)?", value):
                            raise ValueError(
                                f"Valeur non numérique à la mesure {target_row - model.first_data_row + 1}, "
                                f"grandeur {column + 1} : {value[:60]!r}.\n"
                                "Pour coller des noms et unités, sélectionnez la ligne Grandeur ou Unité.")
        except (csv.Error, ValueError) as error:
            QMessageBox.warning(self, "Collage impossible", str(error))
            return
        while model.columnCount() <= max(columns):
            model.add_quantity()
        while model.rowCount() < start.row() + len(rows):
            model.add_row()
        model.edit_cells({(start.row() + r, columns[c]): value for r, row in enumerate(rows)
                          for c, value in enumerate(row)}, "Coller des cellules")
        selection = QItemSelection()
        for column in columns:
            selection.select(model.index(start.row(), column), model.index(start.row() + len(rows) - 1, column))
        self.selectionModel().setCurrentIndex(start, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.selectionModel().select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def contextMenuEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid() and not self.selectionModel().isSelected(index):
            self.setCurrentIndex(index)
        menu = QMenu(self)
        undo = menu.addAction("Annuler\tCtrl+Z", self.model().undo_stack.undo)
        undo.setEnabled(self.model().undo_stack.canUndo())
        redo = menu.addAction("Rétablir\tCtrl+Y", self.model().undo_stack.redo)
        redo.setEnabled(self.model().undo_stack.canRedo())
        menu.addSeparator()
        copy = menu.addAction("Copier\tCtrl+C", self.copy_selection)
        copy.setEnabled(bool(self.selectedIndexes()))
        paste = menu.addAction("Coller\tCtrl+V", self.paste_clipboard)
        paste.setEnabled(self.currentIndex().isValid() and bool(QApplication.clipboard().text()))
        if index.isValid() and index.row() == self.model().name_row:
            menu.addSeparator()
            menu.addAction("Supprimer la grandeur…", lambda: self.delete_quantity(index.column()))
        menu.addSeparator()
        menu.addAction("Nouvelle grandeur", self.add_quantity_requested.emit)
        menu.exec(event.globalPos())

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        index = self.indexAt(event.position().toPoint())
        if (event.button() == Qt.MouseButton.LeftButton and index.isValid()
                and index.row() == self.model().unit_row
                and self.state() != QAbstractItemView.State.EditingState):
            self.edit(index)

    def advance_down(self):
        current = self.currentIndex()
        if not current.isValid():
            return
        if current.row() + 1 == self.model().rowCount():
            self.model().add_row()
        target = self.model().index(current.row() + 1, current.column())
        self.setCurrentIndex(target)
        self.scrollTo(target)

    def keyPressEvent(self, event):
        if self._source:
            super().keyPressEvent(event)
            return
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Undo):
            self.model().undo_stack.undo()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            self.model().undo_stack.redo()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_clipboard()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.advance_down()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.model().edit_cells({(index.row(), index.column()): "" for index in self.selectedIndexes()},
                                    "Effacer des cellules")
            return
        super().keyPressEvent(event)


class DataTab(QWidget):
    """Saisir et nommer les colonnes de mesures expérimentales."""

    def __init__(self):
        super().__init__()
        layout = page_layout(QVBoxLayout(self))
        instructions = help_toggle("Saisie des données · Une grandeur par colonne, une mesure par ligne",
            "Grandeur et Unité : nommez les colonnes. Entrée : descendre · Tab : aller à droite.\n"
            "Ctrl+C / Ctrl+V : copier / coller · Ctrl+Z / Ctrl+Y : annuler / rétablir les modifications de cellules.\n"
            "Glissez un en-tête pour déplacer sa colonne. Clic droit : supprimer une grandeur.\n"
            "Formules : =A1*2 ou =SOMME(A1:A5). A1 = première mesure de A ; $A$1 reste fixe.\n"
            "Tirez le carré de sélection vers le bas pour recopier une formule ou prolonger deux valeurs.\n"
            "Décimales : virgule ou point. Les données restent en mémoire pendant cette session."
        )
        layout.addWidget(instructions)

        self.model = MeasurementsModel(self)
        self.table = MeasurementsTable(self)
        self.table.setModel(self.model)
        self.table.add_quantity_requested.connect(self.add_quantity)
        delegate = MeasurementDelegate(self.table)
        delegate.advance.connect(self.table.advance_down)
        self.table.setItemDelegate(delegate)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(240)
        self.table.setCurrentIndex(self.model.index(0, 0))

        self.add_quantity_button = role(QPushButton("Ajouter une grandeur"), "primary")
        self.add_quantity_button.setToolTip("Ajouter une colonne vide et saisir son nom")
        self.add_quantity_button.setMinimumHeight(34)
        self.add_quantity_button.clicked.connect(self.add_quantity)
        actions = QHBoxLayout()
        actions.addWidget(self.add_quantity_button)
        self.undo_button = QPushButton("Annuler")
        self.redo_button = QPushButton("Rétablir")
        for button, action, signal in ((self.undo_button, self.model.undo_stack.undo, self.model.undo_stack.canUndoChanged),
                                       (self.redo_button, self.model.undo_stack.redo, self.model.undo_stack.canRedoChanged)):
            button.setEnabled(False)
            button.clicked.connect(action)
            signal.connect(button.setEnabled)
            actions.addWidget(button)
        self.undo_button.setToolTip("Ctrl+Z · Annuler la dernière modification du tableau")
        self.redo_button.setToolTip("Ctrl+Y · Rétablir la dernière modification annulée")
        actions.addStretch()
        layout.addLayout(actions)
        formula_row = QHBoxLayout()
        self.cell_address = QLabel("—")
        self.cell_address.setMinimumWidth(70)
        self.formula_bar = QLineEdit()
        self.formula_bar.setAccessibleName("Valeur ou formule de la cellule")
        self.formula_bar.setPlaceholderText("Valeur ou formule, par exemple =A1*2")
        formula_row.addWidget(self.cell_address)
        formula_row.addWidget(QLabel("fx"))
        formula_row.addWidget(self.formula_bar, 1)
        formula_row.addWidget(math_help_button(self, spreadsheet=True))
        layout.addLayout(formula_row)
        self.table.selectionModel().currentChanged.connect(self.update_formula_bar)
        self.model.dataChanged.connect(self.update_formula_bar)
        self.model.columnsRemoved.connect(self.update_formula_bar)
        self.formula_bar.returnPressed.connect(self.apply_formula_bar)
        self.update_formula_bar()
        layout.addWidget(self.table)

    def update_formula_bar(self, *args):
        index = self.table.currentIndex()
        valid = index.isValid() and index.column() < self.model.columnCount()
        self.formula_bar.setEnabled(valid and bool(self.model.flags(index) & Qt.ItemFlag.ItemIsEditable))
        self.cell_address.setText((column_label(index.column()) +
                                  (str(index.row() - 1) if index.row() >= 2 else " · " + ("Nom" if index.row() == 0 else "Unité")))
                                 if valid else "—")
        if not self.formula_bar.hasFocus():
            self.formula_bar.setText(index.data(Qt.ItemDataRole.EditRole) or "" if valid else "")

    def apply_formula_bar(self):
        index = self.table.currentIndex()
        if index.isValid():
            self.model.edit_cells({(index.row(), index.column()): self.formula_bar.text()}, "Modifier une cellule")
            self.table.setFocus()
            self.update_formula_bar()

    def add_quantity(self):
        self.model.add_quantity()
        index = self.model.index(0, self.model.columnCount() - 1)
        self.table.setCurrentIndex(index)
        self.table.scrollTo(index)
        self.table.setFocus()
        self.table.edit(index)
