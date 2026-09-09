"""Commandes Fichier et aperçu d'import CSV."""
import csv
import json
from pathlib import Path
import zipfile
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QMessageBox, QDialog, QVBoxLayout,
                               QHBoxLayout, QLabel, QComboBox, QCheckBox, QTableWidget,
                               QTableWidgetItem, QDialogButtonBox)
from physlab.project import read_project, write_project, read_csv, write_csv
from physlab.ui.project_state import snapshot, restore, restore_views


class CsvImportDialog(QDialog):
    def __init__(self, path, parent):
        super().__init__(parent)
        self.path, self.data = path, None
        self.setWindowTitle('Importer des données CSV')
        self.resize(760, 440)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Les données seront ajoutées dans de nouvelles colonnes du tableur.'))
        row = QHBoxLayout()
        row.addWidget(QLabel('Séparateur'))
        self.separator = QComboBox()
        for label, value in [('Automatique', None), ('Point-virgule ;', ';'), ('Virgule ,', ','), ('Tabulation', '\t')]:
            self.separator.addItem(label, value)
        row.addWidget(self.separator)
        self.header = QCheckBox('La première ligne contient les noms des grandeurs')
        self.header.setChecked(True)
        row.addWidget(self.header)
        layout.addLayout(row)
        self.preview = QTableWidget()
        self.preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.preview)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Importer')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Annuler')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.separator.currentIndexChanged.connect(self.refresh)
        self.header.toggled.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.data = None
        try:
            data = read_csv(self.path, self.separator.currentData(), self.header.isChecked())
            self.preview.setColumnCount(len(data['names']))
            self.preview.setHorizontalHeaderLabels([n + (f' [{u}]' if u else '') for n, u in zip(data['names'], data['units'])])
            self.preview.setRowCount(min(30, len(data['rows'])))
            for r, row in enumerate(data['rows'][:30]):
                for c, value in enumerate(row):
                    self.preview.setItem(r, c, QTableWidgetItem(value))
            self.status.setText(f"{len(data['rows'])} lignes · {len(data['names'])} colonnes · aperçu des 30 premières lignes")
            self.data = data
        except (OSError, ValueError, csv.Error) as error:
            self.status.setText(str(error))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.data is not None)


class ProjectFiles:
    def setup_files(self):
        self.project_path = None
        self._saved_state = None
        self._discard_on_close = False
        menu = self.menuBar().addMenu('Fichier')
        for title, shortcut, callback in (
            ('Nouveau projet', QKeySequence.StandardKey.New, self.new_project),
            ('Ouvrir un projet…', QKeySequence.StandardKey.Open, self.open_project),
            ('Enregistrer', QKeySequence.StandardKey.Save, self.save_project),
            ('Enregistrer sous…', QKeySequence.StandardKey.SaveAs, lambda: self.save_project(save_as=True)),
            ('Importer un CSV…', 'Ctrl+I', self.import_csv),
            ('Exporter le tableur en CSV…', 'Ctrl+E', self.export_csv),
        ):
            action = QAction(title, self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            menu.addAction(action)
        self._saved_state = self.document_signature()

    def document_signature(self):
        state = snapshot(self)
        # La navigation, la lecture vidéo et les dimensions de fenêtre ne modifient pas le travail.
        state.pop('tab', None)
        state.pop('active_graph', None)
        state['video'].pop('index', None)
        state['video'].pop('controls', None)
        for graph in state['graphs']:
            for key in ('geometry', 'view', 'right_view', 'legend'):
                graph.pop(key, None)
        return json.dumps(state, ensure_ascii=False, sort_keys=True)

    def confirm_save(self):
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()
        if self._discard_on_close or self.document_signature() == self._saved_state:
            return True
        answer = QMessageBox.question(self, 'Enregistrer le projet ?',
            'Le projet contient des modifications non enregistrées.',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def save_project(self, checked=False, save_as=False):
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()
        if self.video_tab.loader is not None:
            QMessageBox.information(self, 'Vidéo en préparation', 'Attendez la fin de la préparation de la vidéo avant d’enregistrer.')
            return False
        path = self.project_path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(self, 'Enregistrer le projet', str(path or 'Sans titre.physalyx'), 'Projet Physalyx (*.physalyx)')
            if not path:
                return False
            if not path.lower().endswith('.physalyx'):
                path += '.physalyx'
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            state = snapshot(self)
            write_project(path, state, self.video_tab.cache)
            self.project_path = Path(path)
            self._saved_state = self.document_signature()
            self.setWindowTitle(f'{self.project_path.name} — Physalix')
            self.statusBar().showMessage(f'Projet enregistré : {path}', 8000)
            return True
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            QMessageBox.critical(self, 'Enregistrement impossible', str(error))
            return False
        finally:
            QApplication.restoreOverrideCursor()

    def replace_project(self, state=None, path=None):
        from physlab.ui.main_window import MainWindow
        staging = MainWindow()
        staging._discard_on_close = True
        try:
            if state is not None:
                restore(staging, state, path)
            if not self.confirm_save():
                staging.video_tab.shutdown()
                return False
            self.video_tab.shutdown()
            old = self.takeCentralWidget()
            for name in ('tabs', 'data_tab', 'graph_tab', 'modeling_tab', 'video_tab', 'calculations_tab', 'statistics_tab'):
                setattr(self, name, getattr(staging, name))
            staging.takeCentralWidget()
            self.setCentralWidget(self.tabs)
            self.tabs.currentChanged.disconnect()
            self.tabs.currentChanged.connect(self.update_navigation)
            self.graph_tab.modeling_requested.disconnect()
            self.graph_tab.modeling_requested.connect(lambda: self.tabs.setCurrentWidget(self.modeling_tab))
            self.modeling_tab.graph_requested.disconnect()
            self.modeling_tab.graph_requested.connect(lambda: self.tabs.setCurrentWidget(self.graph_tab))
            old.deleteLater()
            self.project_path = Path(path) if path else None
            self.setWindowTitle(f'{self.project_path.name} — Physalix' if path else 'Physalix')
            if state is not None:
                restore_views(self, state['graphs'])
            self._saved_state = self.document_signature()
            return True
        except Exception:
            staging.video_tab.shutdown()
            raise
        finally:
            staging.deleteLater()

    def new_project(self):
        self.replace_project()

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Ouvrir un projet', str(self.project_path or ''), 'Projet Physalyx (*.physalyx)')
        if not path:
            return
        try:
            state = read_project(path)
            if self.replace_project(state, path):
                self.statusBar().showMessage(f'Projet ouvert : {path}', 8000)
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, zipfile.BadZipFile) as error:
            QMessageBox.critical(self, 'Ouverture impossible', f'Le projet est invalide ou incomplet.\n{error}')

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Importer un CSV', '', 'Données CSV (*.csv *.tsv *.txt);;Tous les fichiers (*)')
        if not path:
            return
        dialog = CsvImportDialog(path, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.append_csv(dialog.data)
            self.tabs.setCurrentWidget(self.data_tab)
            self.statusBar().showMessage('Données CSV importées.', 6000)

    def append_csv(self, data):
        model = self.data_tab.model
        pristine = (model.names == ['x', 'y'] and not any(model.units) and not any(any(r) for r in model.rows)
                    and not model.formulas and not model.calculated_columns)
        count = len(data['names'])
        first = 0 if pristine else model.columnCount()
        while model.columnCount() < first + count:
            model.add_quantity()
        if pristine:
            while model.columnCount() > count:
                model.remove_quantity(model.columnCount()-1)
        while len(model.rows) < len(data['rows']):
            model.add_row()
        used = set(model.names[:first])
        for c, (name, unit) in enumerate(zip(data['names'], data['units']), first):
            original, suffix = name, 2
            while name in used:
                name, suffix = f'{original}_{suffix}', suffix+1
            used.add(name)
            model.setData(model.index(0, c), name)
            model.setData(model.index(1, c), unit)
        # Importer les textes comme valeurs, sans interpréter les cellules CSV comme des formules.
        for r, row in enumerate(data['rows']):
            for c, value in enumerate(row, first):
                model.rows[r][c] = value
        model.dataChanged.emit(model.index(2, first), model.index(len(data['rows'])+1, first+count-1))
        model.undo_stack.clear()

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Exporter les valeurs du tableur', 'donnees.csv', 'Données CSV (*.csv)')
        if not path:
            return
        if not path.lower().endswith('.csv'):
            path += '.csv'
        try:
            snapshot(self)  # Terminer les recalculs en attente avant l'export.
            header = self.data_tab.table.horizontalHeader()
            write_csv(path, self.data_tab.model, [header.logicalIndex(i) for i in range(header.count())])
            self.statusBar().showMessage(f'Tableur exporté : {path}', 8000)
        except (OSError, ValueError, csv.Error) as error:
            QMessageBox.critical(self, 'Export impossible', str(error))
