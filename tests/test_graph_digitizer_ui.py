"""Transfert ciblé de la numérisation vers le tableur et le grapheur."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QSpinBox

from physalix.ui.main_window import MainWindow
from physalix.ui.scientific_symbols import SCIENTIFIC_SYMBOLS


class DigitizerTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.show()
        self.tab = self.window.digitizer_tab
        self.app.processEvents()

    def tearDown(self):
        self.window._discard_on_close = True
        self.window.close()
        self.app.processEvents()

    def test_main_navigation_adds_digitizer_last(self):
        self.window.resize(self.window._navigation_required_width("normal") + 100, 800)
        self.app.processEvents()
        self.assertIs(self.window.tabs.widget(self.window.tabs.count() - 1), self.tab)
        self.assertEqual(self.window.tabs.tabText(self.window.tabs.count() - 1), "Numérisation")

    def test_scientific_symbols_units_and_explicit_actions(self):
        self.window.tabs.setCurrentWidget(self.tab)
        self.app.processEvents()
        symbol_button = self.tab.x_symbol_button
        expected = ("α", "β", "γ", "Δ", "δ", "ε", "θ", "λ", "μ", "ρ", "σ", "φ", "ω")
        self.assertEqual(SCIENTIFIC_SYMBOLS, expected)
        self.assertEqual([action.text() for action in symbol_button.menu().actions()],
                         list(expected))
        self.assertEqual(ord("μ"), 0x03BC)
        self.tab.x_name.setText("Grandeur X")
        next(action for action in symbol_button.menu().actions()
             if action.text() == "σ").trigger()
        self.app.processEvents()
        self.assertEqual(self.tab.x_name.text(), "σ")
        self.assertTrue(self.tab.x_name.hasFocus())
        self.assertIsInstance(self.tab.x_unit, QComboBox)
        self.assertTrue(self.tab.x_unit.isEditable())
        self.tab.x_unit.setEditText("unité personnalisée")
        self.assertEqual(self.tab.unit_text("x"), "unité personnalisée")
        self.assertEqual(self.tab.color_button.text(), "Détecter automatiquement")
        self.assertEqual(self.tab.add_button.text(), "Ajouter manuellement")
        self.assertEqual(self.tab.edit_button.text(), "Corriger / déplacer")
        self.assertFalse(any(spin.isVisible() for spin in self.tab.findChildren(QSpinBox)))

    def test_detection_guidance_and_result_are_explicit(self):
        self.window.tabs.setCurrentWidget(self.tab)
        self.app.processEvents()
        self.tab.image = QImage(100, 100, QImage.Format.Format_RGB32)
        self.tab.image.fill(QColor("white"))
        self.tab.session.set_roi((0, 0, 100, 100))
        self.tab.session.set_axis_marks("x", [((10, 90), 0), ((90, 90), 10)])
        self.tab.session.set_axis_marks("y", [((10, 90), 0), ((10, 10), 10)])
        self.tab.start_color_detection()
        self.assertEqual(self.tab.detection_instruction.text(),
                         "Cliquez sur un point coloré du graphique à détecter.")
        candidates = [(5 + 3 * index, 20) for index in range(25)]
        with patch("physalix.ui.graph_digitizer_tab.detect_colored_markers",
                   return_value=candidates):
            self.tab.detect_color(QColor("red"), QPointF(50, 50))
        self.assertEqual(
            self.tab.detection_instruction.text(),
            "25 points détectés — vérifiez le résultat puis créez les données.")
        QTest.qWait(60)
        visible = self.tab.create_button.visibleRegion().boundingRect()
        self.assertEqual(visible.height(), self.tab.create_button.height())

    def test_calibration_wording_instruction_and_placed_feedback(self):
        self.tab.session.set_roi((0, 0, 100, 100))
        self.tab.value_fields["x"][0].setText("0")
        self.tab.start_calibration("x", 0)
        self.assertEqual(
            self.tab.calibration_status.text(),
            "Cliquez sur la graduation correspondant à cette valeur sur l'axe X.")
        self.tab.canvas_clicked(QPointF(10, 90))
        self.assertEqual(self.tab.mark_buttons["x"][0].text(), "Replacer ✓")
        self.assertIn("1/2 point placé", self.tab.axis_status["x"].text())
        self.tab.value_fields["x"][1].setText("30")
        self.tab.start_calibration("x", 1)
        self.tab.canvas_clicked(QPointF(90, 90))
        self.assertEqual(self.tab.axis_status["x"].text(), "✓ Axe X calibré")

    def test_selected_detected_and_manual_points_can_be_deleted(self):
        detected = self.tab.session.add_point(
            (30, 40), validated=False, automatic=True)
        manual = self.tab.session.add_point(
            (50, 60), validated=True, automatic=False)
        self.tab.refresh_table()
        self.tab.refresh_controls()

        self.assertFalse(self.tab.delete_button.isEnabled())
        self.tab.points_table.selectRow(0)
        self.app.processEvents()
        self.assertTrue(self.tab.delete_button.isEnabled())
        self.tab.delete_selected()
        self.assertIsNone(self.tab.session.point(detected.identifier))
        self.assertIsNotNone(self.tab.session.point(manual.identifier))
        self.assertEqual(self.tab.points_table.rowCount(), 1)

        self.tab.points_table.selectRow(0)
        self.app.processEvents()
        self.assertTrue(self.tab.delete_button.isEnabled())
        self.tab.delete_selected()
        self.assertIsNone(self.tab.session.point(manual.identifier))
        self.assertEqual(self.tab.points_table.rowCount(), 0)
        self.assertFalse(self.tab.delete_button.isEnabled())

    def test_delete_all_points_preserves_graph_setup(self):
        session = self.tab.session
        session.set_roi((5, 10, 100, 80))
        session.set_axis_marks("x", [((10, 80), 0), ((90, 80), 16)])
        session.set_axis_marks("y", [((10, 80), 50), ((10, 20), 230)])
        roi = session.roi
        calibration = session.calibration
        x_marks = list(session.x_marks)
        y_marks = list(session.y_marks)
        self.tab.x_name.setText("Vᵦ")
        self.tab.x_unit.setEditText("mL")
        self.tab.y_name.setText("σ")
        self.tab.y_unit.setEditText("µS·cm⁻¹")
        session.add_point((30, 40), validated=False, automatic=True)
        session.add_point((50, 60), validated=True, automatic=False)
        self.tab.refresh_table()
        self.tab.refresh_controls()

        self.assertTrue(self.tab.delete_all_button.isEnabled())
        self.tab.delete_all()

        self.assertEqual(session.points, [])
        self.assertEqual(self.tab.points_table.rowCount(), 0)
        self.assertIsNone(self.tab.canvas.selected_point)
        self.assertFalse(self.tab.delete_all_button.isEnabled())
        self.assertFalse(self.tab.delete_button.isEnabled())
        self.assertEqual(session.roi, roi)
        self.assertIs(session.calibration, calibration)
        self.assertEqual(session.x_marks, x_marks)
        self.assertEqual(session.y_marks, y_marks)
        self.assertEqual(self.tab.x_name.text(), "Vᵦ")
        self.assertEqual(self.tab.unit_text("x"), "mL")
        self.assertEqual(self.tab.y_name.text(), "σ")
        self.assertEqual(self.tab.unit_text("y"), "µS·cm⁻¹")

    def test_reference_jpeg_images_open_with_qt_decoder(self):
        fixtures = Path(__file__).parent / "fixtures" / "graph_images"
        paths = sorted(fixtures.glob("*.jpg"))
        self.assertEqual(len(paths), 7)
        for path in paths:
            with self.subTest(image=path.name):
                self.assertTrue(self.tab.open_image(path))
                self.assertIn((self.tab.image.width(), self.tab.image.height()),
                              ((1536, 2048), (2048, 1536)))

    def test_validated_points_create_new_columns_and_new_graph(self):
        session = self.tab.session
        session.set_roi((0, 0, 120, 120))
        session.set_axis_marks("x", [((10, 100), 0), ((110, 100), 10)])
        session.set_axis_marks("y", [((10, 100), 0), ((10, 0), 20)])
        session.add_point((30, 75), validated=True)
        rejected = session.add_point((50, 50), validated=False, automatic=True)
        rejected.rejected = True
        session.add_point((70, 25), validated=True)
        self.tab.x_name.setText("x")
        self.tab.x_unit.setEditText("mL")
        self.tab.y_name.setText("y")
        self.tab.y_unit.setEditText("pH")
        self.tab.refresh_table()
        self.tab.refresh_controls()

        initial_graph = self.window.graph_tab.windows[0].graph
        columns, graph = self.tab.create_data_and_graph()
        self.app.processEvents()

        self.assertEqual(columns, (2, 3))
        self.assertEqual(self.window.data_tab.model.names[2:4], ["x_2", "y_2"])
        self.assertEqual(self.window.data_tab.model.units[2:4], ["mL", "pH"])
        self.assertEqual(self.window.data_tab.model.rows[0][2:4], ["2", "5"])
        self.assertEqual(self.window.data_tab.model.rows[1][2:4], ["6", "15"])
        self.assertEqual(len(self.window.graph_tab.windows), 2)
        self.assertIsNot(graph, initial_graph)
        self.assertEqual(graph.series[0].key(), columns)
        self.assertIs(self.window.tabs.currentWidget(), self.window.graph_tab)

    def test_unvalidated_candidates_are_confirmed_and_rejected_points_are_excluded(self):
        session = self.tab.session
        session.set_roi((0, 0, 120, 120))
        session.set_axis_marks("x", [((10, 100), 0), ((110, 100), 10)])
        session.set_axis_marks("y", [((10, 100), 0), ((10, 0), 20)])
        pending = session.add_point((30, 75), validated=False, automatic=True)
        rejected = session.add_point((70, 25), validated=False, automatic=True)
        rejected.rejected = True
        self.tab.refresh_controls()
        self.assertTrue(self.tab.create_button.isEnabled())
        with patch.object(self.tab, "confirm_unvalidated_candidates", return_value=False) as confirm:
            self.assertIsNone(self.tab.create_data_and_graph())
        confirm.assert_called_once_with(1)
        self.assertEqual(self.window.data_tab.model.columnCount(), 2)
        self.assertEqual(len(self.window.graph_tab.windows), 1)
        with patch.object(self.tab, "confirm_unvalidated_candidates", return_value=True) as confirm:
            self.tab.create_data_and_graph()
        confirm.assert_called_once_with(1)
        self.assertEqual(self.window.data_tab.model.rows[0][2:4], ["2", "5"])
        self.assertNotIn("6", [row[2] for row in self.window.data_tab.model.rows])

    def test_transfer_rounds_from_calibration_input_precision(self):
        session = self.tab.session
        session.set_roi((0, 0, 120, 120))
        session.set_axis_marks("x", [((10, 100), 0), ((110, 100), 30)])
        session.set_axis_marks("y", [((10, 100), 0), ((10, 0), 20)])
        self.tab.mark_slots = {
            "x": list(session.x_marks), "y": list(session.y_marks),
        }
        self.tab.mark_texts = {"x": ["0", "30"], "y": ["0", "20"]}
        session.add_point((14.3461947345, 75), validated=True)
        self.tab.refresh_controls()
        self.tab.create_data_and_graph()
        self.assertEqual(self.window.data_tab.model.rows[0][2:4], ["1.3", "5"])

    def test_batch_import_preserves_unicode_metadata(self):
        columns = self.window.data_tab.append_measurements(
            ["Vᵦ", "σ"], ["mL", "µS·cm⁻¹"], [["1", "2,5"]])
        self.assertEqual(columns, (2, 3))
        self.assertEqual(self.window.data_tab.model.names[2:4], ["Vᵦ", "σ"])
        self.assertEqual(self.window.data_tab.model.units[2:4], ["mL", "µS·cm⁻¹"])


if __name__ == "__main__":
    unittest.main()
