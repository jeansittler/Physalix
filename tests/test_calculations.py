"""Dérivées physiques, expressions et recalcul des chaînes de grandeurs."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from physalix.calculations import CalculationEngine, Formula, derivative_unit
from physalix.ui.data_tab import MeasurementsModel
from physalix.ui.main_window import MainWindow


class FormulaTests(unittest.TestCase):
    def test_notations_and_functions(self):
        for expression in ("SQRT(Vx^2 + Vy^2)", "sqrt(Vx² + Vy²)", "sqrt(C1**2 + C2**2)"):
            self.assertEqual(Formula(expression, ["Vx", "Vy"]).evaluate(["3", "4"]), 5)
        self.assertAlmostEqual(Formula("SIN(pi/2) + LN(e) + 1,5", []).evaluate([]), 3.5)
        self.assertEqual(Formula("-2^2", []).evaluate([]), -4)
        self.assertEqual(Formula("2^3^2", []).evaluate([]), 512)
        self.assertEqual(Formula("ABS(-3) + 2×4", []).evaluate([]), 11)

    def test_invalid_and_unsafe_formulas(self):
        for expression in ("__import__('os')", "C1.real", "C1[0]", "[x for x in C1]",
                           "lambda: 1", "sqrt(1, 2)", "unknown + 1", "True", "1e999", "sqrt("):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                Formula(expression, ["X"])
        with self.assertRaises(ValueError):
            Formula("X + 1", ["X", "X"])
        self.assertEqual(Formula("C2", ["X", "X"]).evaluate(["1", "2"]), 2)
        for expression in ("1/0", "sqrt(-1)", "2^101", "exp(1000)"):
            with self.subTest(expression=expression), self.assertRaises((ArithmeticError, ValueError)):
                Formula(expression, []).evaluate([])


class CalculationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_model(self):
        model = MeasurementsModel()
        model.add_quantity()
        model.names = ["X", "Y", "t"]
        model.units = ["m", "m", "s"]
        for i in range(7):
            model.rows[i] = [str(i*i), str(3*i), str(i)]
        return model

    def test_derivative_speed_acceleration_and_rename(self):
        model = self.make_model()
        engine = CalculationEngine(model)
        vx = engine.add("Vx", "m/s", source=0, axis=2)
        vy = engine.add("Vy", "m/s", source=1, axis=2)
        speed = engine.add("v", "m/s", expression="SQRT(Vx² + Vy²)")
        accel = engine.add("ax", "m/s²", source=vx, axis=2)
        self.assertEqual([row[vx] for row in model.rows[:7]], ["", "2", "4", "6", "8", "10", ""])
        self.assertEqual([row[accel] for row in model.rows[:7]], ["", "", "2", "2", "2", "", ""])
        self.assertEqual(model.rows[2][speed], "5")
        self.assertEqual(model.rows[0][speed], "")
        model.setData(model.index(0, vx), "vitesse horizontale")
        model.setData(model.index(5, 0), "15")  # X à t=3, au lieu de 9.
        QTest.qWait(10)
        self.assertEqual(model.rows[2][vx], "7")
        self.assertAlmostEqual(float(model.rows[2][speed]), 58**.5)
        self.assertIn("vitesse horizontale", engine.items[2].formula.description(model.names))
        self.assertFalse(model.setData(model.index(4, vx), "999"))
        self.assertFalse(model.flags(model.index(4, vx)) & Qt.ItemFlag.ItemIsEditable)
        self.assertTrue(model.flags(model.index(0, vx)) & Qt.ItemFlag.ItemIsEditable)

    def test_missing_nonmonotonic_and_variable_intervals(self):
        model = self.make_model()
        engine = CalculationEngine(model)
        column = engine.add("D", "m/s", source=0, axis=2)
        model.rows[2][0] = ""
        engine.recalculate()
        self.assertEqual([model.rows[i][column] for i in (1, 2, 3)], ["", "", ""])
        self.assertEqual(model.rows[4][column], "8")
        model.rows[2][0] = "4"
        model.rows[2][2] = "1"  # Temps répété.
        engine.recalculate()
        self.assertEqual(model.rows[1][column], "")
        self.assertEqual(model.rows[2][column], "")
        model.rows[2][2] = "1.5"
        engine.recalculate()
        self.assertAlmostEqual(float(model.rows[1][column]), 4/1.5)
        self.assertIn("pas variable", engine.items[0].status)

    def test_formula_domain_errors_keep_row_alignment(self):
        model = self.make_model()
        engine = CalculationEngine(model)
        column = engine.add("ratio", "", expression="1/(t-2)")
        self.assertEqual(model.rows[1][column], "-1")
        self.assertEqual(model.rows[2][column], "")
        self.assertEqual(model.rows[3][column], "1")
        self.assertIn("1 erreur", engine.items[0].status)
        before = model.columnCount()
        with self.assertRaises(ValueError):
            engine.add("bad", "", expression="sqrt(X")
        self.assertEqual(model.columnCount(), before)
        constant = engine.add("g", "m/s²", expression="9,81")
        self.assertEqual(model.rows[6][constant], "9.81")
        self.assertEqual(model.rows[7][constant], "")
        self.assertEqual(derivative_unit("m/s", "s"), "m/s²")
        self.assertEqual(derivative_unit("cm", "s"), "cm/s")

    def test_suggested_units_follow_sources_and_manual_unit_is_preserved(self):
        model = self.make_model()
        engine = CalculationEngine(model)
        velocity = engine.add("Vx", "m/s", source=0, axis=2)
        acceleration = engine.add("ax", "m/s²", source=velocity, axis=2)
        model.setData(model.index(1, 0), "cm")
        QTest.qWait(10)
        self.assertEqual(model.units[velocity], "cm/s")
        self.assertEqual(model.units[acceleration], "cm/s²")
        model.setData(model.index(1, velocity), "unité personnalisée")
        QTest.qWait(10)
        model.setData(model.index(1, 0), "mm")
        QTest.qWait(10)
        self.assertEqual(model.units[velocity], "unité personnalisée")

    def test_ui_creation_and_graph_available(self):
        window = MainWindow()
        try:
            window.show()
            tab = window.calculations_tab
            model = window.data_tab.model
            model.add_quantity()
            for i, name in enumerate(("X", "Y", "t")):
                model.setData(model.index(0, i), name)
            for row in range(5):
                for col, value in enumerate((row*row, 3*row, row)):
                    model.setData(model.index(row+2, col), str(value))
            QTest.qWait(10)
            window.tabs.setCurrentWidget(tab)
            tab.source.setCurrentIndex(0)
            tab.axis.setCurrentIndex(2)
            tab.derivative_name.setText("Vx")
            tab.derive_button.click()
            tab.source.setCurrentIndex(1)
            tab.derivative_name.setText("Vy")
            tab.derive_button.click()
            tab.formula_name.setText("v")
            tab.expression.setText("SQRT(Vx^2 + Vy^2)")
            tab.formula_button.click()
            QTest.qWait(10)
            self.assertEqual(model.names[-3:], ["Vx", "Vy", "v"])
            self.assertEqual(model.rows[2][-1], "5")
            self.assertEqual(tab.history.rowCount(), 3)
            self.assertEqual(window.graph_tab.series[0].x_choice.count(), 6)
        finally:
            window._discard_on_close = True
            window.close()
