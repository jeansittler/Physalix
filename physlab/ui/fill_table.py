"""Recopie verticale d'une série numérique à la souris."""

from decimal import Decimal, InvalidOperation, localcontext

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QTableView
from physlab.spreadsheet import translate_formula


def extend_series(texts: list[str], count: int) -> list[str]:
    """Prolonger une suite régulière ; une valeur seule est répétée.

    Decimal évite les artefacts binaires tels que 0,30000000000000004.
    Une sélection vide, trouée ou irrégulière ne définit pas de série.
    """
    if not texts:
        raise ValueError("Sélection vide")
    try:
        numbers = [Decimal(text.replace(",", ".")) for text in texts]
    except InvalidOperation as error:
        raise ValueError("La sélection doit contenir des nombres") from error
    if not all(number.is_finite() for number in numbers):
        raise ValueError("Les nombres doivent être finis")
    with localcontext() as context:
        context.prec = max(28, max(len(n.as_tuple().digits) for n in numbers) + 16)
        step = numbers[1] - numbers[0] if len(numbers) > 1 else Decimal(0)
        if any(b - a != step for a, b in zip(numbers, numbers[1:])):
            raise ValueError("Sélectionnez une suite à pas constant")
        use_comma = any("," in text for text in texts)
        result = []
        for offset in range(1, count + 1):
            value = numbers[-1] + step * offset
            text = format(value, "f")
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            result.append(text.replace(".", ",") if use_comma else text)
        return result


class FillTableView(QTableView):
    """Poignée de recopie pour une sélection verticale contiguë."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._source = None
        self._target_row = None
        self._drag_position = None
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(80)
        self._scroll_timer.timeout.connect(self._auto_scroll)

    def _selected_series(self):
        selection = self.selectionModel()
        if selection is None or self.state() == QAbstractItemView.State.EditingState:
            return None
        ranges = list(selection.selection())
        if len(ranges) != 1:
            return None
        area = ranges[0]
        if area.top() < self.model().first_data_row or area.left() != area.right():
            return None
        if area.left() in self.model().calculated_columns:
            return None
        texts = [self.model().data(self.model().index(row, area.left()), Qt.ItemDataRole.EditRole)
                 for row in range(area.top(), area.bottom() + 1)]
        if not all(text.startswith("=") for text in texts):
            try:
                extend_series(texts, 0)
            except ValueError:
                return None
        return area.top(), area.bottom(), area.left(), texts

    def fill_handle_rect(self):
        """Position de la poignée dans le viewport, ou rectangle vide."""
        source = self._source or self._selected_series()
        if source is None:
            return QRect()
        cell = self.visualRect(self.model().index(source[1], source[2]))
        if not self.viewport().rect().contains(cell.bottomRight()):
            return QRect()
        return QRect(cell.right() - 7, cell.bottom() - 7, 8, 8)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        color = self.palette().highlight().color()
        if self._source and self._target_row > self._source[1]:
            top, _, column, _ = self._source
            preview = self.visualRect(self.model().index(top, column)).united(
                self.visualRect(self.model().index(self._target_row, column)))
            painter.setPen(QPen(color, 2, Qt.PenStyle.DashLine))
            painter.drawRect(preview.adjusted(1, 1, -1, -1))
        handle = self.fill_handle_rect()
        if not handle.isEmpty():
            painter.fillRect(handle, color)
        painter.end()

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self.fill_handle_rect().contains(event.position().toPoint())):
            self._source = self._selected_series()
            self._target_row = self._source[1]
            self._drag_position = event.position().toPoint()
            self._scroll_timer.start()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        position = event.position().toPoint()
        if self._source:
            self._drag_position = position
            self._update_target()
            event.accept()
            return
        self.viewport().setCursor(
            Qt.CursorShape.CrossCursor if self.fill_handle_rect().contains(position)
            else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def _update_target(self):
        y = max(0, min(self._drag_position.y(), self.viewport().height() - 1))
        row = self.rowAt(y)
        if row < 0:
            row = self.model().rowCount() - 1
        self._target_row = max(self._source[1], row)
        self.viewport().update()

    def _auto_scroll(self):
        if self._source is None:
            return
        y = self._drag_position.y()
        bar = self.verticalScrollBar()
        if y >= self.viewport().height() - 16:
            if bar.value() == bar.maximum():
                self.model().add_row()
            bar.setValue(bar.value() + 1)
        elif y < 16:
            bar.setValue(bar.value() - 1)
        self._update_target()

    def mouseReleaseEvent(self, event):
        if self._source and event.button() == Qt.MouseButton.LeftButton:
            self._drag_position = event.position().toPoint()
            self._update_target()
            top, bottom, column, texts = self._source
            target = self._target_row
            self.cancel_fill()
            if all(text.startswith("=") for text in texts):
                values = [translate_formula(texts[(row - top) % len(texts)],
                                             row - (top + (row - top) % len(texts)))
                          for row in range(bottom + 1, target + 1)]
            else:
                values = extend_series(texts, target - bottom)
            self.model().edit_cells({(row, column): value for row, value in enumerate(values, bottom + 1)},
                                    "Recopier des cellules")
            area = QItemSelection(self.model().index(top, column),
                                  self.model().index(target, column))
            self.selectionModel().select(
                area, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def cancel_fill(self):
        self._scroll_timer.stop()
        self._source = None
        self._target_row = None
        self.viewport().unsetCursor()
        self.viewport().update()

    def keyPressEvent(self, event):
        if self._source:
            if event.key() == Qt.Key.Key_Escape:
                self.cancel_fill()
            event.accept()
            return
        super().keyPressEvent(event)

    def hideEvent(self, event):
        self.cancel_fill()
        super().hideEvent(event)
