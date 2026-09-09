"""Conventions lycée partagées et notation scientifique lors des recopies."""
import math
import unittest

from physalix.calculations import Formula, number
from physalix.spreadsheet import CellFormula, translate_formula, remove_formula_column


class UsualFunctionsTests(unittest.TestCase):
    def test_same_conventions_in_both_formula_engines(self):
        cases = [('ln(e)', 1), ('LN(exp(2))', 2), ('log(100)', 2),
                 ('LOG(0,01)', -2), ('log10(1000)', 3), ('exp(0)', 1),
                 ('racine(9)+sqrt(16)', 7), ('abs(-3)', 3),
                 ('sin(pi/2)+cos(0)+tan(0)', 2), ('10^5', 100000),
                 ('8E5', 800000), ('8E+5', 800000), ('2,5E-3', .0025),
                 ('8e5+1.2e-3', 800000.0012)]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                self.assertAlmostEqual(Formula(expression, []).evaluate([]), expected)
                self.assertAlmostEqual(CellFormula('='+expression).evaluate(lambda r,c: 0), expected)

    def test_scientific_literals_are_not_cell_references(self):
        expression = '=8E5*A1+2,5E-3+$E$5+E5'
        self.assertEqual(translate_formula(expression, rows=1), '=8E5*A2+2,5E-3+$E$5+E6')
        self.assertEqual(remove_formula_column(expression, 4), '=8E5*A1+2,5E-3+#REF!+#REF!')
        self.assertEqual(CellFormula('=8E5*A1').references, {'ref_0': ((0, 0), None)})
        self.assertEqual(number('8E5'), 800000)
        self.assertEqual(number('2,5E-3'), .0025)

    def test_invalid_domains_remain_errors(self):
        for expression in ('ln(0)', 'log(-1)', 'sqrt(-1)', 'exp(1000)'):
            for formula in (Formula(expression, []), CellFormula('='+expression)):
                with self.subTest(expression=expression, engine=type(formula).__name__):
                    with self.assertRaises((ValueError, OverflowError)):
                        formula.evaluate([] if isinstance(formula, Formula) else lambda r,c: 0)
