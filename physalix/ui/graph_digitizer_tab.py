"""Onglet de numérisation manuelle et assistée de graphiques en image."""

from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from physalix.graph_digitization import (
    CalibrationError, CalibrationMark, DigitizationSession, calibration_decimal_places,
    detect_colored_markers, format_digitized_value,
)
from physalix.ui.components import help_toggle, label, page_layout, panel, refresh_style, role
from physalix.ui.graph_digitizer_canvas import GraphImageCanvas
from physalix.ui.scientific_symbols import scientific_symbol_field
from physalix.ui.theme import LIGHT
from physalix.ui.units import unit_combo


def parse_number(text):
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError as error:
        raise ValueError("Saisissez une valeur numérique valide.") from error
    if not np.isfinite(value):
        raise ValueError("La valeur doit être finie.")
    return value


def image_array(image):
    converted = image.convertToFormat(QImage.Format.Format_RGB888)
    view = np.frombuffer(converted.bits(), dtype=np.uint8, count=converted.sizeInBytes())
    return view.reshape(converted.height(), converted.bytesPerLine())[:, :converted.width() * 3].reshape(
        converted.height(), converted.width(), 3).copy()


class GraphDigitizerTab(QWidget):
    """Préparer une série dans une session locale, puis la transférer explicitement."""

    COLOR_TOLERANCE = 65

    def __init__(self, data_tab, graph_workspace, parent=None):
        super().__init__(parent)
        self.data_tab = data_tab
        self.graph_workspace = graph_workspace
        self.session = DigitizationSession()
        self.image = QImage()
        self.image_path = None
        self.pending_mark = None
        self.mark_slots = {"x": [None, None], "y": [None, None]}
        self.mark_texts = {"x": [None, None], "y": [None, None]}
        self._refreshing_table = False
        self._transferred = False

        layout = page_layout(QVBoxLayout(self))
        layout.addWidget(help_toggle(
            "Numérisation",
            "1. Ouvrez une image et encadrez le graphique. 2. Placez deux graduations connues sur X, puis deux sur Y.\n"
            "3. Ajoutez les points manuellement ou choisissez la couleur d'un marqueur. "
            "Les points orange sont des candidats à valider ; les points verts seront transférés.\n"
            "Molette : zoom · outil Déplacer : faire glisser l'image. La session temporaire n'est pas enregistrée dans le projet.",
            "Transformer des points visibles sur une image en données expérimentales",
        ))

        actions, actions_layout = panel(kind="toolbar", horizontal=True)
        self.open_button = role(QPushButton("Ouvrir une image…"), "primary")
        self.open_button.clicked.connect(self.choose_image)
        actions_layout.addWidget(self.open_button)
        self.fit_button = QPushButton("Ajuster à la fenêtre")
        self.fit_button.clicked.connect(self.fit_image)
        actions_layout.addWidget(self.fit_button)
        self.pan_button = QPushButton("Déplacer")
        self.roi_button = QPushButton("Encadrer le graphique")
        self.add_button = QPushButton("Ajouter manuellement")
        self.edit_button = QPushButton("Corriger / déplacer")
        for button, mode in ((self.pan_button, "pan"), (self.roi_button, "roi"),
                             (self.add_button, "add"), (self.edit_button, "edit")):
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=mode: self.set_mode(value))
            actions_layout.addWidget(button)
        actions_layout.addStretch()
        layout.addWidget(actions)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = GraphImageCanvas(self.session)
        self.canvas.rectangle_selected.connect(self.set_roi)
        self.canvas.image_clicked.connect(self.canvas_clicked)
        self.canvas.point_selected.connect(self.select_point)
        self.canvas.point_moved.connect(self.point_moved)
        self.canvas.color_selected.connect(self.detect_color)
        self.canvas.pointer_moved.connect(self.update_pointer)
        splitter.addWidget(self.canvas)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(360)
        scroll.setMaximumWidth(470)
        self.side_scroll = scroll
        side = QWidget()
        side.setMinimumWidth(0)
        side.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(LIGHT.small, 0, LIGHT.small, LIGHT.related)
        side_layout.setSpacing(LIGHT.group)
        scroll.setWidget(side)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        layout.addWidget(splitter, 1)

        axes, axes_layout = panel("Axes et calibration")
        metadata = QFormLayout()
        metadata.setContentsMargins(0, 0, 0, 0)
        self.x_name, self.x_unit = QLineEdit("x"), unit_combo()
        self.y_name, self.y_unit = QLineEdit("y"), unit_combo()
        self.x_name.setAccessibleName("Grandeur X")
        self.x_unit.setAccessibleName("Unité X")
        self.y_name.setAccessibleName("Grandeur Y")
        self.y_unit.setAccessibleName("Unité Y")
        x_name_field, self.x_symbol_button = scientific_symbol_field(self.x_name)
        y_name_field, self.y_symbol_button = scientific_symbol_field(self.y_name)
        metadata.addRow("Grandeur X :", x_name_field)
        metadata.addRow("Unité X :", self.x_unit)
        metadata.addRow("Grandeur Y :", y_name_field)
        metadata.addRow("Unité Y :", self.y_unit)
        axes_layout.addLayout(metadata)
        self.value_fields = {"x": [], "y": []}
        self.mark_buttons = {"x": [], "y": []}
        self.axis_status = {}
        for number, axis in enumerate(("x", "y"), 1):
            axes_layout.addWidget(role(QLabel(f"{number}. Calibrer l'axe {axis.upper()}"), "cardTitle"))
            for index in range(2):
                row = QHBoxLayout()
                row.addWidget(label(f"Valeur {index + 1}", "fieldLabel"))
                field = QLineEdit()
                field.setPlaceholderText("Valeur")
                field.setAccessibleName(f"Valeur de calibration {axis.upper()}{index + 1}")
                self.value_fields[axis].append(field)
                row.addWidget(field, 1)
                button = QPushButton("Placer")
                button.clicked.connect(
                    lambda checked=False, a=axis, i=index: self.start_calibration(a, i))
                self.mark_buttons[axis].append(button)
                row.addWidget(button)
                axes_layout.addLayout(row)
            self.axis_status[axis] = role(QLabel("0/2 point placé"), "caption")
            axes_layout.addWidget(self.axis_status[axis])
        self.calibration_status = role(QLabel("Encadrez d'abord la zone du graphique."), "caption")
        self.calibration_status.setWordWrap(True)
        axes_layout.addWidget(self.calibration_status)
        side_layout.addWidget(axes)

        detection, detection_layout = panel("Points")
        detection_actions = QHBoxLayout()
        self.color_button = QPushButton("Détecter automatiquement")
        self.color_button.clicked.connect(self.start_color_detection)
        detection_actions.addWidget(self.color_button, 1)
        detection_layout.addLayout(detection_actions)
        validation_actions = QHBoxLayout()
        self.validate_all_button = QPushButton("Tout valider")
        self.validate_all_button.clicked.connect(self.validate_all)
        validation_actions.addWidget(self.validate_all_button)
        self.delete_all_button = role(QPushButton("Tout supprimer"), "danger")
        self.delete_all_button.clicked.connect(self.delete_all)
        validation_actions.addWidget(self.delete_all_button)
        detection_layout.addLayout(validation_actions)
        self.delete_button = role(QPushButton("Supprimer le point"), "danger")
        self.delete_button.clicked.connect(self.delete_selected)
        detection_layout.addWidget(self.delete_button)
        self.detection_instruction = role(
            QLabel("Détection automatique : choisissez l'action puis cliquez sur un point coloré."),
            "context",
        )
        self.detection_instruction.setWordWrap(True)
        detection_layout.addWidget(self.detection_instruction)
        self.points_table = QTableWidget(0, 4)
        self.points_table.setHorizontalHeaderLabels(["Validé", "X", "Y", "Origine"])
        self.points_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.points_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.points_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.points_table.itemChanged.connect(self.validation_changed)
        self.points_table.itemSelectionChanged.connect(self.table_selection_changed)
        self.points_table.verticalHeader().hide()
        self.points_table.setMinimumHeight(125)
        self.points_table.setMaximumHeight(180)
        self.points_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        detection_layout.addWidget(self.points_table)
        self.pointer_label = role(QLabel("Coordonnées : calibration incomplète"), "caption")
        self.pointer_label.setWordWrap(True)
        detection_layout.addWidget(self.pointer_label)
        self.status = role(QLabel("La session reste temporaire jusqu'au transfert."), "caption")
        self.status.setWordWrap(True)
        detection_layout.addWidget(self.status)
        self.create_button = role(QPushButton("Créer les données et le graphique"), "primary")
        self.create_button.clicked.connect(self.create_data_and_graph)
        detection_layout.addWidget(self.create_button)
        side_layout.addWidget(detection)
        side_layout.addSpacing(LIGHT.section)
        side_layout.addStretch()

        self.set_mode("pan")
        self.refresh_controls()

    def unit_text(self, axis):
        return (self.x_unit if axis == "x" else self.y_unit).currentText().strip()

    def display_value(self, axis, value):
        texts = [text for text in self.mark_texts[axis] if text is not None]
        places = calibration_decimal_places(texts) if texts else 4
        return format_digitized_value(value, places)

    def set_mode(self, mode):
        buttons = {"pan": self.pan_button, "roi": self.roi_button,
                   "add": self.add_button, "edit": self.edit_button}
        for name, button in buttons.items():
            button.blockSignals(True)
            button.setChecked(name == mode)
            button.blockSignals(False)
        self.canvas.set_mode(mode)
        hints = {
            "pan": "Faites glisser l'image pour la déplacer ; utilisez la molette pour zoomer.",
            "roi": "Tracez un rectangle autour de la zone utile du graphique.",
            "add": "Cliquez dans la zone du graphique pour ajouter un point validé.",
            "edit": "Faites glisser un point pour le corriger, ou sélectionnez-le pour le supprimer.",
            "color": "Cliquez au centre d'un marqueur coloré représentatif.",
            "calibration": "Cliquez précisément sur la graduation indiquée.",
        }
        self.status.setText(hints.get(mode, ""))

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir une image de graphique", "", "Images (*.jpg *.jpeg *.png)")
        if path:
            self.open_image(path)

    def open_image(self, path):
        path = Path(path)
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            QMessageBox.warning(self, "Format non pris en charge", "Choisissez une image JPEG ou PNG.")
            return False
        try:
            if path.stat().st_size > 64 * 1024 ** 2:
                raise ValueError("L'image dépasse la taille maximale de 64 Mo.")
        except OSError as error:
            QMessageBox.critical(self, "Ouverture impossible", str(error))
            return False
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            QMessageBox.critical(self, "Ouverture impossible", reader.errorString())
            return False
        if image.width() * image.height() > 50_000_000:
            QMessageBox.warning(self, "Image trop grande", "L'image dépasse la limite de 50 millions de pixels.")
            return False
        self.image = image
        self.image_path = path
        self.session.reset()
        self.mark_slots = {"x": [None, None], "y": [None, None]}
        self.mark_texts = {"x": [None, None], "y": [None, None]}
        self.pending_mark = None
        self._transferred = False
        self.canvas.set_image(image)
        self.set_mode("roi")
        self.refresh_table()
        self.refresh_controls()
        self.status.setText(f"{path.name} · {image.width()} × {image.height()} px. Encadrez le graphique.")
        return True

    def fit_image(self):
        self.canvas.fit_to_window()

    def set_roi(self, rectangle):
        self.session.set_roi((rectangle.x(), rectangle.y(), rectangle.width(), rectangle.height()))
        self.mark_slots = {"x": [None, None], "y": [None, None]}
        self.mark_texts = {"x": [None, None], "y": [None, None]}
        self.pending_mark = None
        self._transferred = False
        self.set_mode("pan")
        self.refresh_table()
        self.refresh_controls()
        self.status.setText("Zone définie. Saisissez une valeur puis placez chaque graduation de calibration.")

    def start_calibration(self, axis, index):
        if self.session.roi is None:
            QMessageBox.information(self, "Zone nécessaire", "Encadrez d'abord la zone du graphique.")
            return
        try:
            value = parse_number(self.value_fields[axis][index].text())
        except ValueError as error:
            QMessageBox.warning(self, "Valeur incorrecte", str(error))
            self.value_fields[axis][index].setFocus()
            return
        self.pending_mark = axis, index, value
        self.set_mode("calibration")
        instruction = f"Cliquez sur la graduation correspondant à cette valeur sur l'axe {axis.upper()}."
        self.calibration_status.setText(instruction)
        self.calibration_status.setProperty("role", "context")
        refresh_style(self.calibration_status)
        self.status.setText(instruction)

    def canvas_clicked(self, point):
        if self.pending_mark is not None:
            axis, index, value = self.pending_mark
            self.mark_slots[axis][index] = CalibrationMark((point.x(), point.y()), value)
            self.mark_texts[axis][index] = self.value_fields[axis][index].text().strip()
            self.pending_mark = None
            try:
                marks = [mark for mark in self.mark_slots[axis] if mark is not None]
                self.session.set_axis_marks(axis, marks)
            except CalibrationError as error:
                QMessageBox.warning(self, "Calibration impossible", str(error))
            self._transferred = False
            self.set_mode("pan")
            self.refresh_table()
            self.refresh_controls()
            self.canvas.update()
            return
        if self.canvas.mode == "add":
            try:
                self.session.add_point(point, validated=True)
            except ValueError as error:
                self.status.setText(str(error))
                return
            self._transferred = False
            self.refresh_table()
            self.refresh_controls()
            self.canvas.update()

    def start_color_detection(self):
        if self.image.isNull() or self.session.roi is None:
            QMessageBox.information(self, "Image incomplète",
                                    "Ouvrez une image et encadrez d'abord la zone du graphique.")
            return
        if self.session.calibration is None:
            QMessageBox.information(
                self, "Calibration nécessaire",
                "Calibrez les axes X et Y avant de détecter automatiquement les points.")
            return
        self.set_mode("color")
        self.detection_instruction.setText("Cliquez sur un point coloré du graphique à détecter.")
        self.detection_instruction.setProperty("role", "context")
        refresh_style(self.detection_instruction)

    def detect_color(self, color, sample_point):
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            pixels = detect_colored_markers(
                image_array(self.image), self.session.roi,
                (color.red(), color.green(), color.blue()), self.COLOR_TOLERANCE,
                sample_point=sample_point, calibration=self.session.calibration)
            existing = [np.asarray(point.pixel) for point in self.session.points]
            unique = [pixel for pixel in pixels
                      if not any(np.linalg.norm(np.asarray(pixel) - stored) < 7 for stored in existing)]
            self.session.add_candidates(unique)
        except ValueError as error:
            QMessageBox.warning(self, "Détection impossible", str(error))
            unique = []
        finally:
            QApplication.restoreOverrideCursor()
        self._transferred = False
        self.set_mode("edit")
        self.refresh_table()
        self.refresh_controls()
        self.canvas.update()
        if unique:
            noun = "point détecté" if len(unique) == 1 else "points détectés"
            self.detection_instruction.setText(
                f"{len(unique)} {noun} — vérifiez le résultat puis créez les données.")
            self.status.setText("Les candidats peuvent être déplacés, supprimés ou validés individuellement.")
            QTimer.singleShot(0, self.show_create_button)
            QTimer.singleShot(50, self.show_create_button)
        else:
            self.detection_instruction.setText(
                "Aucun nouveau marqueur trouvé. Réessayez sur un point bien coloré ou ajoutez-le manuellement.")
            self.status.setText("La détection est terminée.")

    def show_create_button(self):
        self.side_scroll.ensureWidgetVisible(self.create_button, 0, 16)
        # La création est la dernière étape : après détection, montrer sans ambiguïté
        # le bas compact du panneau plutôt que laisser quelques pixels hors champ.
        bar = self.side_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def validate_all(self):
        for point in self.session.points:
            self.session.set_validated(point.identifier, True)
        self._transferred = False
        self.refresh_table()
        self.refresh_controls()
        self.canvas.update()

    def point_moved(self, identifier, point):
        try:
            self.session.move_point(identifier, point)
        except ValueError as error:
            self.status.setText(str(error))
        self._transferred = False
        self.refresh_table()
        self.refresh_controls()

    def select_point(self, identifier):
        for row in range(self.points_table.rowCount()):
            item = self.points_table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == identifier:
                self.points_table.selectRow(row)
                break

    def table_selection_changed(self):
        identifier = self.selected_point_identifier()
        self.canvas.selected_point = identifier
        self.canvas.update()
        self.delete_button.setEnabled(identifier is not None)

    def selected_point_identifier(self):
        rows = self.points_table.selectionModel().selectedRows()
        if not rows:
            return None
        identifier = rows[0].data(Qt.ItemDataRole.UserRole)
        return identifier if self.session.point(identifier) is not None else None

    def delete_selected(self):
        identifier = self.selected_point_identifier()
        if identifier is None:
            self.refresh_controls()
            return
        self.session.remove_point(identifier)
        self.canvas.selected_point = None
        self._transferred = False
        self.refresh_table()
        self.points_table.clearSelection()
        self.refresh_controls()
        self.canvas.update()

    def delete_all(self):
        if not self.session.points:
            return
        self.session.points.clear()
        self.canvas.selected_point = None
        self._transferred = False
        self.refresh_table()
        self.points_table.clearSelection()
        self.refresh_controls()
        self.canvas.update()
        self.status.setText("Tous les points ont été supprimés.")

    def validation_changed(self, item):
        if self._refreshing_table or item.column() != 0:
            return
        identifier = item.data(Qt.ItemDataRole.UserRole)
        validated = item.checkState() == Qt.CheckState.Checked
        point = self.session.point(identifier)
        self.session.set_validated(identifier, validated)
        if point is not None and not validated:
            point.rejected = True
        self._transferred = False
        self.refresh_table()
        self.refresh_controls()
        self.canvas.update()

    def refresh_table(self):
        self._refreshing_table = True
        try:
            entries = []
            if self.session.calibration is not None:
                entries = self.session.converted_points(validated_only=False)
            else:
                entries = [((None, None), point) for point in self.session.points]
            self.points_table.setRowCount(len(entries))
            for row, ((x, y), point) in enumerate(entries):
                check = QTableWidgetItem()
                check.setData(Qt.ItemDataRole.UserRole, point.identifier)
                check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                               Qt.ItemFlag.ItemIsUserCheckable)
                check.setCheckState(Qt.CheckState.Checked if point.validated else Qt.CheckState.Unchecked)
                self.points_table.setItem(row, 0, check)
                for column, axis, value in ((1, "x", x), (2, "y", y)):
                    item = QTableWidgetItem("—" if value is None else self.display_value(axis, value))
                    item.setData(Qt.ItemDataRole.UserRole, point.identifier)
                    self.points_table.setItem(row, column, item)
                source = QTableWidgetItem("Détecté" if point.automatic else "Manuel")
                source.setData(Qt.ItemDataRole.UserRole, point.identifier)
                self.points_table.setItem(row, 3, source)
        finally:
            self._refreshing_table = False

    def update_pointer(self, point):
        if point is None or self.session.calibration is None:
            self.pointer_label.setText("Coordonnées : calibration incomplète"
                                       if self.session.calibration is None else "Coordonnées : —")
            return
        x, y = self.session.calibration.convert(point)
        x_unit = f" {self.unit_text('x')}" if self.unit_text("x") else ""
        y_unit = f" {self.unit_text('y')}" if self.unit_text("y") else ""
        self.pointer_label.setText(
            f"{self.x_name.text().strip() or 'x'} = {self.display_value('x', x)}{x_unit} · "
            f"{self.y_name.text().strip() or 'y'} = {self.display_value('y', y)}{y_unit}")

    def refresh_controls(self):
        ready_image = not self.image.isNull()
        has_roi = self.session.roi is not None
        calibrated = self.session.calibration is not None
        transferable = sum(point.validated or (point.automatic and not point.rejected)
                           for point in self.session.points)
        for button in (self.fit_button, self.pan_button, self.roi_button):
            button.setEnabled(ready_image)
        for button in (self.add_button, self.edit_button):
            button.setEnabled(has_roi)
        self.color_button.setEnabled(calibrated)
        self.validate_all_button.setEnabled(bool(self.session.points))
        self.delete_button.setEnabled(self.selected_point_identifier() is not None)
        self.delete_all_button.setEnabled(bool(self.session.points))
        self.create_button.setEnabled(calibrated and transferable > 0 and not self._transferred)
        for axis in ("x", "y"):
            placed = sum(mark is not None for mark in self.mark_slots[axis])
            for index, button in enumerate(self.mark_buttons[axis]):
                button.setText("Replacer ✓" if self.mark_slots[axis][index] is not None else "Placer")
            status = self.axis_status[axis]
            status.setText(f"✓ Axe {axis.upper()} calibré" if placed == 2
                           else f"{placed}/2 point{'s' if placed != 1 else ''} placé{'s' if placed != 1 else ''}")
            status.setProperty("role", "success" if placed == 2 else "caption")
            refresh_style(status)
        if calibrated:
            self.calibration_status.setText("Calibration complète · transformation affine active.")
            self.calibration_status.setProperty("role", "success")
        else:
            count = len(self.session.x_marks) + len(self.session.y_marks)
            self.calibration_status.setText(
                f"Calibration : {count}/4 point(s) placé(s)." if has_roi
                else "Encadrez d'abord la zone du graphique.")
            self.calibration_status.setProperty("role", "caption")
        refresh_style(self.calibration_status)

    def create_data_and_graph(self):
        if self.session.calibration is None:
            QMessageBox.information(self, "Calibration incomplète",
                                    "Placez deux points connus sur chaque axe.")
            return
        converted = self.session.converted_points(validated_only=False)
        pending = [point for values, point in converted
                   if point.automatic and not point.validated and not point.rejected]
        if pending and not self.confirm_unvalidated_candidates(len(pending)):
            return
        converted = [(values, point) for values, point in converted
                     if point.validated or (point.automatic and not point.rejected)]
        if not converted:
            QMessageBox.information(self, "Aucun point validé",
                                    "Validez au moins un point ou conservez un candidat détecté.")
            return
        x_name = self.x_name.text().strip() or "x"
        y_name = self.y_name.text().strip() or "y"
        rows = [[self.display_value("x", values[0]), self.display_value("y", values[1])]
                for values, point in converted]
        columns = self.data_tab.append_measurements(
            [x_name, y_name], [self.unit_text("x"), self.unit_text("y")], rows)
        graph = self.graph_workspace.add_data_graph(*columns, title=f"{y_name} en fonction de {x_name}")
        self._transferred = True
        self.refresh_controls()
        window = self.window()
        if hasattr(window, "tabs"):
            window.tabs.setCurrentWidget(self.graph_workspace)
            window.statusBar().showMessage(
                f"{len(rows)} point(s) transféré(s) dans le tableur et un nouveau graphique créé.", 8000)
        return columns, graph

    def confirm_unvalidated_candidates(self, count):
        noun = "point détecté n'a" if count == 1 else "points détectés n'ont"
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle("Utiliser les points détectés ?")
        dialog.setText(
            f"{count} {noun} pas été validé{'s' if count != 1 else ''} individuellement. "
            "Voulez-vous les utiliser pour créer les données ?")
        use = dialog.addButton(
            f"Utiliser {'ce point' if count == 1 else f'les {count} points'}",
            QMessageBox.ButtonRole.AcceptRole,
        )
        back = dialog.addButton("Revenir vérifier", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(back)
        dialog.exec()
        return dialog.clickedButton() is use
