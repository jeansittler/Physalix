"""Vérifier les ajustements sur des données connues et les cas dégénérés."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
from PySide6.QtWidgets import QApplication

from physalix.fitting import Expression, fit_model, parse_parameters
from physalix.ui.main_window import MainWindow


class FittingTests(unittest.TestCase):
    def test_polynomial_models(self):
        x = np.linspace(-3, 4, 30)
        for kind, y, expected in (
            ("constant", x*0+7, [7]), ("linear", 3*x, [3]),
            ("affine", -2*x+4, [-2, 4]), ("square", 2*x*x, [2]),
            ("quadratic", -4*x*x+3*x+2, [-4, 3, 2]),
        ):
            with self.subTest(kind=kind):
                result = fit_model(x, y, kind)
                np.testing.assert_allclose(list(result.parameters.values()), expected, atol=1e-10)
                self.assertLess(result.rmse, 1e-10)
                self.assertEqual(result.r_squared is None, kind == "constant")

    def test_nonlinear_models_with_shifted_origin_and_irregular_samples(self):
        x = 4+np.linspace(0, 1, 80)**1.2*5
        for kind, y, expected in (
            ("charge", 0.3+5*(1-np.exp(-(x-4)/1.2)), [5, 1.2, 0.3]),
            ("discharge", 0.3+5*np.exp(-(x-4)/1.2), [5, 1.2, 0.3]),
            ("exponential", 2*np.exp(0.4*(x-4))+1, [2, 0.4, 1]),
            ("sine", 3*np.sin(5.3*(x-4)+0.7)+2, [3, 5.3, 0.7, 2]),
        ):
            with self.subTest(kind=kind):
                result = fit_model(x, y, kind)
                np.testing.assert_allclose(list(result.parameters.values()), expected, atol=1e-5)
                self.assertLess(result.rmse, 1e-7)

    def test_quality_and_interval(self):
        x = np.arange(6.)
        y = np.array([1., 2, 4, 4, 7, 100])
        result = fit_model(x, y, "affine", interval=(0, 4))
        residual = y[:5]-(result.parameters["a"]*x[:5]+result.parameters["b"])
        sse = sum(residual**2)
        self.assertEqual(result.count, 5)
        self.assertAlmostEqual(result.rmse, np.sqrt(sse/5))
        self.assertAlmostEqual(result.residual_std, np.sqrt(sse/3))
        self.assertAlmostEqual(result.r_squared, 1-sse/sum((y[:5]-y[:5].mean())**2))
        self.assertIsNone(fit_model([0, 1], [1, 3], "affine").residual_std)
        self.assertLess(fit_model([1, 2, 3], [4, 4, 4.1], "linear").r_squared, 0)

    def test_custom_named_axis_and_decimal_comma(self):
        x = np.linspace(0, 3, 20)
        result = fit_model(x, 2*x*x+3, "custom", axis_name="Temps",
                           expression="a*Temps²+c", initial="a=0,5 ; c=0")
        np.testing.assert_allclose(list(result.parameters.values()), [2, 3], atol=1e-7)
        result = fit_model(x, x*0+4, "custom", expression="c", initial="c=1")
        self.assertAlmostEqual(result.parameters['c'], 4)

    def test_invalid_data_and_unsafe_expressions(self):
        for expression in ("__import__('os')", "x.__class__", "x[0]", "[a for a in x]", "open(x)", "a*z"):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                Expression(expression, ["a"])
        for text in ("x=1", "a=nan", "a=1;a=2", "pi=1", "a"):
            with self.assertRaises(ValueError):
                parse_parameters(text)
        for xs, ys, kind in (([], [], "affine"), ([1, 1, 1], [2, 3, 4], "quadratic"),
                             ([0], [2], "linear"), ([0, 1], [2, np.nan], "affine")):
            with self.assertRaises(ValueError):
                fit_model(xs, ys, kind)
        with self.assertRaises(ValueError):
            fit_model([-2, -1, 0], [1, 2, 3], "custom", expression="a*log(x)", initial="a=1")
        with self.assertRaises(ValueError):
            fit_model([0, 1, 2], [1, 2, 3], "affine", interval=(5, 6))


class ModelingInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_model_lifecycle_selection_and_series_isolation(self):
        window = MainWindow()
        graph, tab, model = window.graph_tab, window.modeling_tab, window.data_tab.model
        try:
            model.rows = [[str(x), str(2*x+3)] for x in range(8)]
            graph.refresh_plot()
            first = graph.series[0]
            tab.calculate()
            self.assertTrue(first.fits)
            curve = first.fits[0].curve
            self.assertEqual(len(curve.getData()[0]), 600)
            self.assertIn("R² = 1", tab.result_text.toPlainText())
            first.connect_points.setChecked(True)
            self.assertTrue(first.fits)
            second = graph.add_series()
            self.assertFalse(second.fits)
            first.visible.setChecked(False)
            self.assertFalse(curve.isVisible())
            self.assertTrue(first.fits)
            first.visible.setChecked(True)
            tab.series_choice.setCurrentIndex(tab.series_choice.findData(first.number))
            tab.range_check.setChecked(True)
            graph.fit_region.setRegion((2, 5))
            tab.calculate()
            self.assertEqual(first.fits[-1].result.count, 4)
            self.assertEqual(first.fits[-1].result.x[0], 2)
            model.rows[0][1] = "42"
            graph.refresh_plot()
            self.assertFalse(first.fits)
            self.assertNotIn(curve, graph.plot.getPlotItem().items)
            tab.calculate()
            self.assertTrue(first.fits)
            first.x_choice.setCurrentIndex(1)
            self.assertFalse(first.fits)
            tab.calculate()
            tab.remove_fit()
            self.assertFalse(first.fits)
            graph.remove_series(first)
            self.assertIs(tab.current_series(), second)
        finally:
            window._discard_on_close = True
            window.close()

    def test_interval_editor_closes_after_calculation_and_restores_bounds(self):
        window = MainWindow()
        graph, tab, model = window.graph_tab, window.modeling_tab, window.data_tab.model
        try:
            window.show()
            model.rows = [[str(x), str(2*x+1)] for x in range(10)]
            graph.refresh_plot()
            tab.range_check.setChecked(True)
            self.assertFalse(graph.fit_region.isVisible())
            tab.select_button.click()
            self.assertIs(window.tabs.currentWidget(), graph)
            self.assertTrue(graph.fit_region.isVisible())
            self.assertTrue(graph.interval_tools.isVisible())
            graph.fit_region.setRegion((2, 6))
            graph.calculate_interval_button.click()
            self.assertIs(window.tabs.currentWidget(), graph)
            self.assertFalse(graph.fit_region.isVisible())
            self.assertFalse(graph.interval_tools.isVisible())
            self.assertEqual(tab.current_fit().settings['interval'], (2, 6))
            self.assertEqual(tab.current_fit().result.count, 5)
            window.tabs.setCurrentWidget(tab)
            tab.select_button.click()
            self.assertTrue(graph.fit_region.isVisible())
            self.assertEqual(graph.fit_region.getRegion(), (2, 6))
            graph.fit_region.setRegion((3, 7))
            window.tabs.setCurrentWidget(tab)
            tab.fit_button.click()
            self.assertFalse(graph.fit_region.isVisible())
            self.assertEqual(tab.current_fit().settings['interval'], (3, 7))
            self.assertEqual(len(graph.series[0].fits), 1)
            tab.select_button.click()
            graph.fit_region.setRegion((20, 30))
            graph.calculate_interval_button.click()
            self.assertTrue(graph.fit_region.isVisible())
            self.assertIn('impossible', graph.interval_hint.text())
            self.assertEqual(tab.current_fit().settings['interval'], (3, 7))
            graph.hide_interval_button.click()
            self.assertFalse(graph.fit_region.isVisible())
        finally:
            window._discard_on_close = True
            window.close()

    def test_two_affine_intervals_and_independent_updates(self):
        window = MainWindow()
        graph, tab, model = window.graph_tab, window.modeling_tab, window.data_tab.model
        try:
            # Deux branches séparées ; intersection (10, 2) sous tous les points mesurés.
            model.rows = [[str(x), str(12-x if x < 10 else x-8)]
                          for x in [0, 1, 2, 3, 17, 18, 19, 20]]
            graph.refresh_plot()
            series = graph.series[0]
            tab.range_check.setChecked(True)
            graph.fit_region.setRegion((0, 3))
            tab.calculate()
            first = series.fits[0]
            tab.new_fit_button.click()
            graph.fit_region.setRegion((17, 20))
            tab.calculate()
            second = series.fits[1]
            self.assertEqual(len(series.fits), 2)
            self.assertEqual(first.result.count, 4)
            self.assertEqual(second.result.count, 4)
            self.assertNotEqual(first.color, second.color)
            self.assertEqual(len(graph.legend.items), 3)
            for fit in series.fits:
                self.assertTrue(fit.extension.isVisible())
                self.assertEqual(fit.extension.getData()[0][0], 0)
                self.assertEqual(fit.extension.getData()[0][-1], 20)
                self.assertAlmostEqual(fit.result.parameters['a']*10+fit.result.parameters['b'], 2)
            self.assertLess(graph.plot.viewRange()[1][0], 2)
            tab.fit_choice.setCurrentIndex(tab.fit_choice.findData(first.number))
            self.assertEqual(tab.interval(), (0, 3))
            graph.fit_region.setRegion((0, 2))
            tab.calculate()
            self.assertEqual(len(series.fits), 2)
            self.assertEqual(first.result.count, 3)
            self.assertEqual(second.result.count, 4)
            tab.extend_check.setChecked(False)
            self.assertFalse(first.extension.isVisible())
            self.assertTrue(second.extension.isVisible())
            series.visible.setChecked(False)
            self.assertFalse(second.curve.isVisible())
            self.assertFalse(second.extension.isVisible())
            series.visible.setChecked(True)
            tab.fit_choice.setCurrentIndex(tab.fit_choice.findData(first.number))
            tab.remove_fit()
            self.assertEqual(series.fits, [second])
            self.assertNotIn(first.curve, graph.plot.getPlotItem().items)
            self.assertNotIn(first.extension, graph.plot.getPlotItem().items)
            model.rows[0][1] = '13'
            graph.refresh_plot()
            self.assertFalse(series.fits)
            self.assertNotIn(second.extension, graph.plot.getPlotItem().items)
        finally:
            window._discard_on_close = True
            window.close()


if __name__ == "__main__":
    unittest.main()
