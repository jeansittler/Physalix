"""Lecteur vidéo avec navigation exacte parmi les images décodées."""

from pathlib import Path
from math import hypot

from PySide6.QtCore import QElapsedTimer, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from physlab.video import prepare_video
from physlab.ui.data_tab import MeasurementsModel
from physlab.ui.video_canvas import Magnifier, VideoCanvas
from physlab.ui.video_tracking import CalibrationDialog, TrackingSession
from physlab.ui.components import workspace_layout, panel, label, role


class VideoLoader(QThread):
    progress = Signal(int)

    def __init__(self, path, parent):
        super().__init__(parent)
        self.path = path
        self.cache = None
        self.error = None

    def run(self):
        try:
            self.cache = prepare_video(self.path, self.isInterruptionRequested, self.progress.emit)
        except Exception as error:
            self.error = str(error)


class VideoTab(QWidget):
    def __init__(self, model=None):
        super().__init__()
        self.model = model if model is not None else MeasurementsModel(self)
        self.tracking = TrackingSession(self.model)
        self.mode = None
        self.correction_return = None
        self.cache = None
        self.loader = None
        self.index = 0
        self.playing = False
        self.pixmap = QPixmap()
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._tick)
        layout = workspace_layout(self, 760, 560)
        toolbar = QHBoxLayout()
        self.open_button = role(QPushButton("Ouvrir une vidéo…"), "primary")
        self.open_button.clicked.connect(self.choose_video)
        self.cancel_button = QPushButton("Annuler la préparation")
        self.cancel_button.clicked.connect(self.cancel_loading)
        self.cancel_button.hide()
        toolbar.addWidget(label("Fichier", "caption"))
        toolbar.addWidget(self.open_button)
        toolbar.addWidget(self.cancel_button)
        toolbar.addStretch()
        axes_label = QLabel("Sens des axes")
        self.axes_choice = QComboBox()
        axes_label.setBuddy(self.axes_choice)
        self.axes_choice.setAccessibleName("Sens des axes X et Y")
        for title, directions in (("X droite · Y haut", (1, 1)), ("X droite · Y bas", (1, -1)),
                                   ("X gauche · Y haut", (-1, 1)), ("X gauche · Y bas", (-1, -1))):
            self.axes_choice.addItem(title, directions)
        self.axes_choice.setToolTip("Les coordonnées des points déjà acquis sont recalculées dans le nouveau repère.")
        self.axes_choice.currentIndexChanged.connect(self.change_axes)
        toolbar.addWidget(axes_label)
        toolbar.addWidget(self.axes_choice)
        layout.addLayout(toolbar)
        self.status = QLabel("Ouvrez une vidéo pour commencer. Lecture sans son.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.calibrate_button = QPushButton("Définir l'étalon")
        self.origin_button = QPushButton("Définir l'origine")
        self.track_button = role(QPushButton("Commencer le pointage"), "primary")
        self.undo_button = role(QPushButton("Annuler la dernière action"), "danger")
        self.calibrate_button.clicked.connect(lambda: self.set_mode("scale"))
        self.origin_button.clicked.connect(lambda: self.set_mode("origin"))
        self.track_button.clicked.connect(lambda: self.set_mode(None if self.mode == "track" else "track"))
        self.undo_button.clicked.connect(self.undo_point)
        for title, buttons in (("Étalonnage", (self.calibrate_button, self.origin_button)),
                               ("Pointage", (self.track_button, self.undo_button))):
            group, group_layout = panel()
            group_layout.addWidget(label(title, "caption"))
            row = QHBoxLayout()
            for button in buttons:
                row.addWidget(button)
            group_layout.addLayout(row)
            actions.addWidget(group)
        layout.addLayout(actions)
        correction_row = QHBoxLayout()
        self.correct_button = QPushButton("Corriger un point")
        self.correct_button.clicked.connect(self.toggle_correction)
        self.point_choice = QComboBox()
        self.point_choice.setMinimumContentsLength(25)
        self.point_choice.setAccessibleName("Point à corriger")
        self.point_choice.activated.connect(self.choose_point)
        correction_row.addWidget(self.correct_button)
        correction_row.addWidget(self.point_choice)
        self.direction_label = QLabel("Direction de l'étalon")
        self.calibration_direction = QComboBox()
        self.calibration_direction.setAccessibleName("Direction de l'étalon")
        self.direction_label.setBuddy(self.calibration_direction)
        for title, direction in (("Horizontal", "horizontal"), ("Vertical", "vertical"), ("Libre (diagonale)", "free")):
            self.calibration_direction.addItem(title, direction)
        self.calibration_direction.currentIndexChanged.connect(self.change_calibration_direction)
        correction_row.addWidget(self.direction_label)
        correction_row.addWidget(self.calibration_direction)
        correction_row.addStretch()
        layout.addLayout(correction_row)
        self.tracking_info = QLabel()
        self.tracking_info.setWordWrap(True)
        layout.addWidget(self.tracking_info)
        self.hint = QLabel("Définissez l'étalon puis l'origine sur l'image de votre choix.")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.screen = VideoCanvas()
        self.screen.clicked.connect(self.image_clicked)
        self.screen.point_selected.connect(self.select_point)
        view = QHBoxLayout()
        view.addWidget(self.screen, 1)
        self.magnifier = Magnifier(self.screen)
        magnifier_panel, magnifier_layout = panel("Loupe ×6")
        magnifier_layout.addWidget(self.magnifier)
        magnifier_layout.addWidget(label("Survolez la vidéo pour viser avec précision.", "muted"))
        magnifier_panel.setFixedWidth(174)
        view.addWidget(magnifier_panel, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(view, 1)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self.seek)
        layout.addWidget(self.slider)
        controls = QHBoxLayout()
        controls.addWidget(label("Lecture", "caption"))
        self.restart_button = QPushButton("Retour au début")
        self.restart_button.setToolTip("Revenir à la première image et mettre la vidéo en pause, en conservant l'étalonnage et les points.")
        self.restart_button.clicked.connect(self.restart_video)
        controls.addWidget(self.restart_button)
        self.previous = QPushButton("Image précédente")
        self.play_button = QPushButton("Lire")
        self.next = QPushButton("Image suivante")
        self.previous.clicked.connect(lambda: self.seek(self.index - 1))
        self.next.clicked.connect(lambda: self.seek(self.index + 1))
        self.play_button.clicked.connect(self.toggle_play)
        for button in (self.previous, self.play_button, self.next):
            controls.addWidget(button)
        self.position = QLabel("Image — · t = — s")
        controls.addWidget(self.position)
        controls.addStretch()
        layout.addLayout(controls)
        for message in (self.status, self.hint, self.position):
            role(message, "muted")
        role(self.tracking_info, "caption")
        for key, action in (("Left", lambda: self.seek(self.index - 1)),
                            ("Right", lambda: self.seek(self.index + 1)),
                            ("Space", self.toggle_play), ("Escape", self.escape_mode)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(action)
        self._controls()

    def _controls(self):
        ready = self.cache is not None and self.loader is None
        self.slider.setEnabled(ready)
        self.restart_button.setEnabled(ready)
        self.axes_choice.setEnabled(ready)
        self.axes_choice.blockSignals(True)
        directions = (self.tracking.x_direction, self.tracking.y_direction)
        self.axes_choice.setCurrentIndex(next(i for i in range(self.axes_choice.count())
                                              if tuple(self.axes_choice.itemData(i)) == directions))
        self.axes_choice.blockSignals(False)
        self.play_button.setEnabled(ready and len(self.cache.times) > 1)
        self.previous.setEnabled(ready and self.index > 0)
        self.next.setEnabled(ready and self.index < len(self.cache.times) - 1)
        self.calibrate_button.setEnabled(ready)
        self.direction_label.setVisible(self.mode == "scale")
        self.calibration_direction.setVisible(self.mode == "scale")
        self.calibration_direction.setEnabled(ready)
        self.origin_button.setEnabled(ready)
        self.track_button.setEnabled(ready and self.tracking.scale is not None and self.tracking.origin is not None)
        self.undo_button.setEnabled(ready and bool(self.tracking.history))
        correcting = self.mode in ("select", "edit")
        self.correct_button.setEnabled(ready and bool(self.tracking.points))
        self.correct_button.setText("Revenir au pointage" if correcting else "Corriger un point")
        self.point_choice.setVisible(correcting)
        self.point_choice.setEnabled(ready and correcting)
        self.point_choice.blockSignals(True)
        self.point_choice.clear()
        self.point_choice.addItem("Choisir un point…", None)
        for index, (_, timestamp) in sorted(self.tracking.points.items()):
            self.point_choice.addItem(f"Image {index + 1} · t = {timestamp:.6g} s", index)
        if self.mode == "edit":
            self.point_choice.setCurrentIndex(self.point_choice.findData(self.index))
        self.point_choice.blockSignals(False)
        self.screen.active = ready and self.mode is not None
        self.screen.selecting = self.mode == "select"
        self.screen.setCursor(Qt.CursorShape.PointingHandCursor if self.screen.selecting else
                              Qt.CursorShape.CrossCursor if self.screen.active else Qt.CursorShape.ArrowCursor)
        self.track_button.setText("Arrêter le pointage" if self.mode == "track" else "Commencer le pointage")
        self.screen.origin = self.tracking.origin
        self.screen.x_direction = self.tracking.x_direction
        self.screen.y_direction = self.tracking.y_direction
        self.screen.ruler = self.tracking.ruler
        self.screen.points = {i: value[0] for i, value in self.tracking.points.items()}
        # L'avance automatique conserve le dernier point bien visible.
        highlight = self.index if self.index in self.tracking.points else next(
            (i for i, _ in reversed(self.tracking.history) if i in self.tracking.points), None)
        self.screen.highlight_index = highlight
        stored = self.tracking.points.get(highlight)
        self.screen.point = stored[0] if stored else None
        self.screen.update()
        scale = (f"Étalon : {self.tracking.length:g} {self.tracking.unit}"
                 if self.tracking.scale is not None else "Étalon : à définir")
        origin = "Origine définie" if self.tracking.origin is not None else "Origine : à définir"
        horizontal = "droite" if self.tracking.x_direction == 1 else "gauche"
        vertical = "haut" if self.tracking.y_direction == 1 else "bas"
        self.tracking_info.setText(f"{scale} · {origin} · {len(self.tracking.points)} point(s) · x vers la {horizontal}, y vers le {vertical}")

    def restart_video(self):
        if self.cache is None or self.loader is not None:
            return
        self.set_mode(None)
        self.seek(0)

    def change_axes(self, *args):
        if self.cache is None or self.loader is not None:
            return
        self.tracking.set_axes(*self.axes_choice.currentData())
        self._controls()

    def set_mode(self, mode):
        if mode is not None and (self.cache is None or self.loader is not None):
            return
        if mode == "track" and (self.tracking.origin is None or self.tracking.scale is None):
            return
        self.pause()
        if mode not in ("select", "edit"):
            self.correction_return = None
        self.mode = mode
        self.screen.anchor = None
        hints = {
            "scale": "Cliquez sur le début de l'étalon, déplacez la flèche puis cliquez sur son extrémité. Direction horizontale par défaut ; choisissez Vertical ou Libre si besoin. Échap pour annuler.",
            "origin": "Cliquez à l'emplacement de x = 0 et y = 0. Échap pour annuler.",
            "track": "Cliquez sur l'objet : le point est enregistré et l'image suivante apparaît. Échap pour arrêter.",
            "select": "Choisissez une marque sur la vidéo ou un point dans la liste. Son image s'affichera pour le corriger.",
            "edit": f"Image {self.index + 1} : cliquez à la position corrigée. Seul ce point sera modifié. Échap pour annuler la sélection.",
            None: "Commencez le pointage ou utilisez « Corriger un point » pour modifier une mesure existante.",
        }
        self.hint.setText(hints[mode])
        self._controls()

    def change_calibration_direction(self, *args):
        self.screen.calibration_direction = self.calibration_direction.currentData()
        self.screen.hovered.emit(self.screen.calibration_point(self.screen.pointer))
        self.screen.update()

    def toggle_correction(self):
        if self.mode in ("select", "edit"):
            target = self.correction_return
            self.set_mode(None)
            if target is not None:
                index, mode = target
                self.seek(index)
                self.set_mode(mode)
        elif self.tracking.points:
            target = (self.index, "track" if self.mode == "track" else None)
            self.set_mode("select")
            self.correction_return = target

    def escape_mode(self):
        if self.mode == "edit":
            self.set_mode("select")
        elif self.mode == "select":
            self.toggle_correction()
        else:
            self.set_mode(None)

    def choose_point(self, choice):
        index = self.point_choice.itemData(choice)
        if index is not None:
            self.select_point(index)

    def select_point(self, index):
        if self.mode not in ("select", "edit") or index not in self.tracking.points:
            return
        self.seek(index)
        self.set_mode("edit")

    def image_clicked(self, point):
        if self.cache is None or self.loader is not None:
            return
        if self.mode == "scale":
            if self.screen.anchor is None:
                self.screen.anchor = point
                self.hint.setText("Cliquez sur la seconde extrémité de l'étalon. Échap pour annuler.")
                self.screen.update()
                return
            start = self.screen.anchor
            point = self.screen.calibration_point(point)
            if hypot(point.x() - start.x(), point.y() - start.y()) < 1:
                self.hint.setText("La longueur doit couvrir au moins un pixel dans la direction choisie. Cliquez plus loin ou changez de direction.")
                return
            dialog = CalibrationDialog(self, self.tracking.unit)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.tracking.calibrate(start, point, dialog.length.value(), dialog.unit.currentText())
            self.set_mode(None)
        elif self.mode == "origin":
            self.tracking.set_origin(point)
            self.set_mode(None)
        elif self.mode == "edit":
            if self.index not in self.tracking.points:
                return
            self.tracking.record(self.index, point, self.tracking.points[self.index][1])
            self.set_mode("select")
            self.hint.setText(f"Point de l'image {self.index + 1} corrigé. Choisissez un autre point ou revenez au pointage. Vous pouvez annuler la dernière action.")
        elif self.mode == "track":
            self.tracking.record(self.index, point, self.cache.times[self.index])
            if self.index < len(self.cache.times) - 1:
                self._show_frame(self.index + 1)
            else:
                self.set_mode(None)
                self.hint.setText("Dernière image pointée. Les mesures x, y et t sont disponibles dans Données et Graphique.")

    def undo_point(self):
        self.set_mode(None)
        index = self.tracking.undo()
        if index is not None:
            self.seek(index)
        self._controls()

    def choose_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir une vidéo", "",
            "Vidéos (*.avi *.mp4 *.m4v *.mov *.mkv *.mpg *.mpeg *.wmv *.webm *.flv *.mts *.m2ts *.ogv);;Tous les fichiers (*)")
        if path:
            self.open_video(path)

    def open_video(self, path):
        if self.loader is not None:
            return
        self.pause()
        self.set_mode(None)
        self.status.setText(f"Préparation de {Path(path).name}… Cache temporaire limité à 4 Go.")
        self.open_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.loader = VideoLoader(path, self)
        self.loader.progress.connect(lambda count: self.status.setText(
            f"Préparation de {Path(path).name} : {count} images décodées…"))
        self.loader.finished.connect(self._loaded)
        self._controls()
        self.loader.start()

    def cancel_loading(self):
        if self.loader:
            self.loader.requestInterruption()
            self.cancel_button.setEnabled(False)

    def _loaded(self):
        worker = self.loader
        if worker is None:
            return
        self.loader = None
        self.open_button.setEnabled(True)
        self.cancel_button.hide()
        if worker.isInterruptionRequested():
            if worker.cache:
                worker.cache.close()
            self.status.setText("Préparation annulée.")
        elif worker.error:
            self.status.setText(f"Impossible d'ouvrir la vidéo : {worker.error}")
        elif worker.cache:
            if self.cache:
                self.cache.close()
            self.cache = worker.cache
            self.tracking = TrackingSession(self.model)
            self.mode = None
            self.screen.anchor = None
            self.calibration_direction.setCurrentIndex(0)
            self.hint.setText("Définissez l'étalon puis l'origine sur l'image de votre choix.")
            self.slider.blockSignals(True)
            self.slider.setRange(0, len(self.cache.times) - 1)
            self.slider.blockSignals(False)
            warning = " · Temps estimés : horodatages manquants." if self.cache.estimated_times else ""
            self.status.setText(f"{Path(worker.path).name} · {self.cache.width} × {self.cache.height} · Lecture sans son.{warning}")
            self._show_frame(0)
        worker.deleteLater()
        self._controls()

    def seek(self, index):
        if self.cache is None or self.loader is not None:
            return
        self.pause()
        if self.mode in ("scale", "origin"):
            self.set_mode(None)
        elif self.mode == "edit":
            self.set_mode("select")
        self._show_frame(max(0, min(index, len(self.cache.times) - 1)))

    def _show_frame(self, index):
        self.index = index
        self.pixmap = QPixmap(self.cache.path(index))
        self._scale_image()
        self.slider.blockSignals(True)
        self.slider.setValue(index)
        self.slider.blockSignals(False)
        self.position.setText(f"Image {index + 1} / {len(self.cache.times)} · t = {self.cache.times[index]:.6f} s")
        self._controls()

    def _scale_image(self):
        if not self.pixmap.isNull():
            self.screen.setPixmap(self.pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_image()

    def toggle_play(self):
        if self.cache is None or self.loader is not None or len(self.cache.times) < 2:
            return
        if self.playing:
            self.pause()
            return
        self.set_mode(None)
        if self.index == len(self.cache.times) - 1:
            self._show_frame(0)
        self.playing = True
        self.play_button.setText("Pause")
        self.start_time = self.cache.times[self.index]
        self.clock.start()
        self._schedule()

    def _schedule(self):
        if self.index >= len(self.cache.times) - 1:
            self.pause()
            return
        delay = (self.cache.times[self.index + 1] - self.start_time) * 1000 - self.clock.elapsed()
        self.timer.start(max(1, min(round(delay), 2147483647)))

    def _tick(self):
        if self.playing:
            self._show_frame(self.index + 1)
            self._schedule()

    def pause(self):
        self.timer.stop()
        self.playing = False
        self.play_button.setText("Lire")

    def shutdown(self):
        self.pause()
        if self.loader:
            self.loader.requestInterruption()
            self.loader.wait()
            if self.loader.cache:
                self.loader.cache.close()
            self.loader.deleteLater()
            self.loader = None
        if self.cache:
            self.cache.close()
            self.cache = None
