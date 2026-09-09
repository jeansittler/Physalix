"""Sauvegardes réelles, liens recalculables et échanges CSV."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog
from physalix.fitting import fit_model
from physalix.project import read_project, write_project, read_csv, write_csv, atomic_write
from physalix.ui.main_window import MainWindow
from physalix.ui.project_state import snapshot, restore


class ProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.windows = [self.window]
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'expérience.physalix'

    def tearDown(self):
        for window in self.windows:
            window._discard_on_close = True
            window.close()
        self.app.processEvents()
        self.directory.cleanup()

    def populated(self):
        w = self.window
        m = w.data_tab.model
        for r, row in enumerate([['0', '1'], ['1', '3'], ['2', '5'], ['3', '7']]):
            for c, value in enumerate(row):
                m.setData(m.index(r+2, c), value)
        w.calculations_tab.engine.add('double', 'V', expression='C2*2')
        w.calculations_tab.engine.add('pente', 'V/s', source=1, axis=0)
        m.add_quantity()
        m.setData(m.index(2, 4), '=B1+1')
        g = w.graph_tab.active_graph
        g.set_model(g.series[0], fit_model([0,1,2,3], [1,3,5,7], 'affine'), 'affine', {'extend': True})
        w.modeling_tab.sync_fits(selected=1)
        second = w.graph_tab.add_graph()
        second.series[0].y_choice.setCurrentIndex(2)
        second.series[0].y_axis.setCurrentIndex(1)
        second.series[0].connect_points.setChecked(True)
        second.series[0].set_curve_color('#123456')
        w.graph_tab.windows[1].setWindowTitle('Tension doublée')
        w.data_tab.table.horizontalHeader().moveSection(2, 0)
        self.app.processEvents()
        return w

    def test_roundtrip_and_live_calculations(self):
        w = self.populated()
        state = snapshot(w)
        write_project(self.path, state)
        v = MainWindow()
        self.windows.append(v)
        restore(v, read_project(self.path), self.path)
        self.app.processEvents()
        self.assertEqual(len(v.graph_tab.windows), 2)
        self.assertEqual(v.graph_tab.windows[1].windowTitle(), 'Tension doublée')
        self.assertEqual(v.data_tab.model.rows, w.data_tab.model.rows)
        self.assertEqual(v.data_tab.model.formulas, {(0, 4): '=B1+1'})
        first = v.graph_tab.windows[0].graph
        self.assertEqual(len(first.series[0].fits), 1)
        self.assertAlmostEqual(first.series[0].fits[0].result.parameters['a'], 2)
        second = v.graph_tab.windows[1].graph
        self.assertEqual(second.series[0].color.name(), '#123456')
        self.assertEqual(second.series[0].y_axis.currentIndex(), 1)
        self.assertTrue(second.series[0].connect_points.isChecked())
        self.assertEqual(v.data_tab.table.horizontalHeader().logicalIndex(0), 2)
        m = v.data_tab.model
        m.setData(m.index(2, 1), '10')
        self.app.processEvents()
        self.assertEqual(m.rows[0][2], '20')
        self.assertEqual(m.rows[0][4], '11')
        self.assertFalse(first.series[0].fits)  # Invalidation normale après modification des mesures.

    def legacy_project(self):
        """Build an authentic version-1 legacy archive, independent of the writer."""
        path = self.path.with_suffix('.physalyx')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('project.json', json.dumps({
                'format': 'Physalyx', 'version': 1, 'state': snapshot(self.window)}))
        return path

    def test_legacy_open_and_save_migrates_without_changing_original(self):
        legacy = self.legacy_project()
        original = legacy.read_bytes()
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(legacy), '')) as dialog:
            self.window.open_project()
        self.assertIn('*.physalix', dialog.call_args.args[3])
        self.assertIn('*.physalyx', dialog.call_args.args[3])
        self.assertEqual(self.window.project_path, legacy)
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(self.path), '')) as dialog:
            self.assertTrue(self.window.save_project())
        self.assertEqual(dialog.call_args.args[2], str(self.path))
        self.assertEqual(self.window.project_path, self.path)
        self.assertEqual(legacy.read_bytes(), original)
        with zipfile.ZipFile(self.path) as archive:
            document = json.loads(archive.read('project.json'))
        self.assertEqual(document['format'], 'Physalix')
        self.assertEqual(document['version'], 1)
        self.assertEqual(read_project(self.path), read_project(legacy))
        with patch.object(QFileDialog, 'getSaveFileName') as dialog:
            self.assertTrue(self.window.save_project())
            dialog.assert_not_called()

    def test_cancel_legacy_migration_preserves_path_and_file(self):
        legacy = self.legacy_project()
        self.window.replace_project(read_project(legacy), legacy)
        with patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')):
            self.assertFalse(self.window.save_project())
        self.assertEqual(self.window.project_path, legacy)
        self.assertFalse(self.path.exists())

    def test_save_suffixes_and_reopen(self):
        for suffix in ('', '.physalix', '.PHYSALIX', '.physalyx', '.PHYSALYX'):
            with self.subTest(suffix=suffix):
                selected = self.path.with_suffix(suffix)
                with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(selected), '')):
                    self.assertTrue(self.window.save_project(save_as=True))
                self.assertEqual(self.window.project_path, self.path)
                self.assertEqual(read_project(self.path), snapshot(self.window))
                self.path.unlink()

    def test_normalized_destination_does_not_overwrite_without_confirmation(self):
        self.path.write_bytes(b'keep me')
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(self.path.with_suffix('')), '')), \
                patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            self.assertFalse(self.window.save_project())
        self.assertEqual(self.path.read_bytes(), b'keep me')

    def test_unknown_format_and_future_version_are_rejected(self):
        for name, version in [('unknown', 1), ('Physalix', 2), ('Physalyx', 2)]:
            with self.subTest(name=name, version=version):
                with zipfile.ZipFile(self.path, 'w') as archive:
                    archive.writestr('project.json', json.dumps({'format': name, 'version': version, 'state': {}}))
                with self.assertRaises(ValueError):
                    read_project(self.path)

    def test_atomic_failure_keeps_previous_file(self):
        self.path.write_text('original', encoding='utf-8')
        def fail(path):
            Path(path).write_text('partial')
            raise OSError('disk full')
        with self.assertRaises(OSError):
            atomic_write(self.path, fail)
        self.assertEqual(self.path.read_text(), 'original')

    def test_invalid_project_does_not_replace_current_work(self):
        w = self.populated()
        old = w.data_tab.model
        state = snapshot(w)
        state['graphs'][0]['series'][0]['controls']['x_choice'] = 999
        with self.assertRaises(ValueError):
            w.replace_project(state)
        self.assertIs(w.data_tab.model, old)

    def test_save_cancel_and_discard(self):
        w = self.window
        w.data_tab.model.setData(w.data_tab.model.index(2, 0), '3')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(w.confirm_save())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Save), patch.object(
                QFileDialog, 'getSaveFileName', return_value=('', '')):
            self.assertFalse(w.confirm_save())
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(self.path), '')):
            self.assertTrue(w.save_project())
        self.assertTrue(w.confirm_save())

    def test_replace_project(self):
        state = snapshot(self.populated())
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.window.replace_project(state))
        self.app.processEvents()
        self.assertEqual(len(self.window.graph_tab.windows), 2)
        self.assertEqual(len(self.window.calculations_tab.engine.items), 2)
        self.assertEqual(self.window.document_signature(), self.window._saved_state)

    def test_csv_decimal_quotes_headers_blanks_and_append(self):
        path = Path(self.directory.name) / 'mesures.csv'
        path.write_text('Temps [s];Tension [V]\n0;1,25\n1;\n2;"texte; cité"\n', encoding='utf-8-sig')
        data = read_csv(path)
        self.assertEqual(data['units'], ['s', 'V'])
        self.assertEqual(data['rows'][2][1], 'texte; cité')
        w = self.window
        w.append_csv(data)
        w.calculations_tab.engine.add('double', 'V', expression='C2*2')
        self.app.processEvents()
        write_csv(path, w.data_tab.model)
        values = read_csv(path)
        self.assertEqual(values['rows'][0], ['0', '1,25', '2,5'])
        w.append_csv(data)
        self.assertEqual(w.data_tab.model.names, ['Temps', 'Tension', 'double', 'Temps_2', 'Tension_2'])
        self.assertEqual(w.data_tab.model.rows[0][:3], ['0', '1,25', '2.5'])

    def test_csv_no_headers_and_literal_formulas(self):
        path = Path(self.directory.name) / 'mesures.csv'
        path.write_text('0,1.5\n1,2.5\n', encoding='utf-8')
        self.assertEqual(read_csv(path, header=False)['rows'][0], ['0', '1.5'])
        self.window.append_csv({'names': ['a','b'], 'units': ['', ''], 'rows': [['=1+2', '-2']]})
        self.assertFalse(self.window.data_tab.model.formulas)
        write_csv(path, self.window.data_tab.model)
        self.assertEqual(read_csv(path)['rows'][0], ["'=1+2", '-2'])

    def test_video_embedded_with_calibration(self):
        from physalix.video import VideoCache
        from PySide6.QtGui import QImage
        video = self.window.video_tab
        video.cache = VideoCache(tempfile.TemporaryDirectory(), [0.0], 20, 20, False)
        image = QImage(20,20,QImage.Format.Format_RGB32)
        image.fill(0)
        image.save(video.cache.path(0))
        video.tracking.origin = QPointF(3,4)
        video.tracking.scale = .1
        video.tracking.length = 1.0
        video.tracking.points = {0: (QPointF(5,6), 0.0)}
        write_project(self.path, snapshot(self.window), video.cache)
        v = MainWindow()
        self.windows.append(v)
        restore(v, read_project(self.path), self.path)
        self.assertEqual(v.video_tab.tracking.origin, QPointF(3,4))
        self.assertEqual(v.video_tab.tracking.points[0][0], QPointF(5,6))
        self.assertFalse(v.video_tab.pixmap.isNull())

    def test_curve_tools_and_zoom_roundtrip(self):
        w = self.populated()
        graph = w.graph_tab.windows[0].graph
        graph.curve_guides_tool.open_tool('tangent')
        graph.curve_guides_tool.source.setCurrentIndex(1)
        graph.curve_guides_tool.x.setValue(1.5)
        graph.curve_guides_tool.asymptote_on.setChecked(True)
        graph.curve_guides_tool.level.setValue(9)
        graph.plot.setRange(xRange=(1,2), yRange=(2,7), padding=0)
        state = snapshot(w)
        v = MainWindow()
        self.windows.append(v)
        restore(v, state)
        self.app.processEvents()
        tool = v.graph_tab.windows[0].graph.curve_guides_tool
        self.assertTrue(tool.active)
        self.assertTrue(tool.asymptote_on.isChecked())
        self.assertEqual(tool.source.currentIndex(), 1)
        self.assertEqual(tool.x.value(), 1.5)
        self.assertEqual(tool.level.value(), 9)
        self.assertEqual(v.graph_tab.windows[0].graph.plot.viewRange(), state['graphs'][0]['view'])

    def test_empty_table_roundtrip(self):
        model = self.window.data_tab.model
        model.remove_quantity(1)
        model.remove_quantity(0)
        v = MainWindow()
        self.windows.append(v)
        restore(v, snapshot(self.window))
        self.assertEqual(v.data_tab.model.columnCount(), 0)


if __name__ == '__main__':
    unittest.main()
