"""Formules de cellules : analyse limitée, références A1 et recopie relative."""

import ast
import math
import re

from physalix.calculations import FUNCTIONS


REFERENCE = r"\$?[A-Za-z]{1,5}\$?[1-9][0-9]*"
REFERENCES = re.compile(rf"(?<![\w$])({REFERENCE})(?:\s*:\s*({REFERENCE}))?(?![\w$]|\s*\()")


def column_label(column):
    label = ""
    while column >= 0:
        column, remainder = divmod(column, 26)
        label = chr(65 + remainder) + label
        column -= 1
    return label


def cell_position(reference):
    match = re.fullmatch(r"(\$?)([A-Za-z]+)(\$?)([1-9][0-9]*)", reference)
    column = 0
    for char in match[2].upper():
        column = column * 26 + ord(char) - 64
    return int(match[4]) - 1, column - 1


def translate_formula(expression, rows=0, columns=0):
    def translate(reference):
        match = re.fullmatch(r"(\$?)([A-Za-z]+)(\$?)([1-9][0-9]*)", reference)
        row, column = cell_position(reference)
        row += 0 if match[3] else rows
        column += 0 if match[1] else columns
        if min(row, column) < 0:
            return "#REF!"
        return f"{match[1]}{column_label(column)}{match[3]}{row + 1}"
    return REFERENCES.sub(lambda m: translate(m[1]) + (":" + translate(m[2]) if m[2] else ""), expression)


def remove_formula_column(expression, removed):
    def replace(match):
        def shift(reference):
            row, column = cell_position(reference)
            if column == removed:
                return "#REF!"
            parts = re.fullmatch(r"(\$?)([A-Za-z]+)(\$?)([1-9][0-9]*)", reference)
            return f"{parts[1]}{column_label(column - (column > removed))}{parts[3]}{row + 1}"
        return shift(match[1]) + (":" + shift(match[2]) if match[2] else "")
    return REFERENCES.sub(replace, expression)


class CellError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class CellFormula:
    def __init__(self, text):
        if len(text) > 2000:
            raise ValueError("Formule trop longue (2 000 caractères maximum).")
        if "#REF!" in text:
            raise CellError("#REF!", "La formule désigne une cellule supprimée ou une référence hors tableau.")
        self.references = {}
        def reference(match):
            start = cell_position(match[1])
            end = cell_position(match[2]) if match[2] else None
            if end and (abs(end[0] - start[0]) + 1) * (abs(end[1] - start[1]) + 1) > 10000:
                raise ValueError("Une plage est limitée à 10 000 cellules.")
            name = f"ref_{len(self.references)}"
            self.references[name] = (start, end)
            return name
        # Interdire les identifiants internes avant leur insertion par le parseur.
        if "_" in text:
            raise ValueError("Identifiant non autorisé.")
        expression = REFERENCES.sub(reference, text[1:])
        expression = expression.replace("^", "**").replace("²", "**2").replace("³", "**3")
        expression = expression.replace("×", "*").replace("÷", "/").replace("−", "-")
        expression = re.sub(r"(?<=\d),(?=\d)", ".", expression).replace(";", ",")
        try:
            self.tree = ast.parse(expression.strip(), mode="eval").body
        except (SyntaxError, RecursionError):
            raise ValueError("Formule incorrecte. Exemple : =A1*2 ou =SOMME(A1:A5).") from None
        if len(list(ast.walk(self.tree))) > 200:
            raise ValueError("Formule trop complexe.")
        self.functions = dict(FUNCTIONS, racine=math.sqrt, ln=math.log)
        self.aggregates = {"somme", "sum", "moyenne", "average", "min", "max"}
        def validate(node, depth=0):
            if depth > 30:
                raise ValueError("Trop de parenthèses imbriquées.")
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                if not math.isfinite(float(node.value)):
                    raise ValueError("Nombre non fini.")
            elif isinstance(node, ast.Name) and (node.id in self.references or node.id.lower() in ("pi", "e")):
                pass
            elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
                validate(node.left, depth + 1)
                validate(node.right, depth + 1)
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                validate(node.operand, depth + 1)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
                name = node.func.id.lower()
                if not ((name in self.functions and len(node.args) == 1) or (name in self.aggregates and node.args)):
                    raise ValueError("Fonction inconnue ou nombre d'arguments incorrect.")
                for arg in node.args:
                    validate(arg, depth + 1)
            else:
                raise ValueError("Utilisez les références A1, +, −, *, /, ^ et les fonctions mathématiques.")
        validate(self.tree)

    def evaluate(self, resolve):
        def visit(node):
            if isinstance(node, ast.Constant):
                return float(node.value)
            if isinstance(node, ast.Name):
                if node.id not in self.references:
                    return math.pi if node.id.lower() == "pi" else math.e
                start, end = self.references[node.id]
                if end is None:
                    return resolve(*start)
                return [resolve(r, c) for r in range(min(start[0], end[0]), max(start[0], end[0]) + 1)
                        for c in range(min(start[1], end[1]), max(start[1], end[1]) + 1)
                        if not getattr(resolve, "is_blank", lambda r, c: False)(r, c)]
            if isinstance(node, ast.UnaryOp):
                value = visit(node.operand)
                return -value if isinstance(node.op, ast.USub) else +value
            if isinstance(node, ast.Call):
                name = node.func.id.lower()
                args = [visit(arg) for arg in node.args]
                if name in self.functions:
                    return self.functions[name](*args)
                values = [v for arg in args for v in (arg if isinstance(arg, list) else [arg])]
                if name in ("somme", "sum"):
                    return sum(values)
                if name in ("moyenne", "average"):
                    return sum(values) / len(values)
                return min(values) if name == "min" else max(values)
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            if isinstance(node.op, ast.Div): return left / right
            if abs(right) > 100:
                raise ValueError("Exposant limité à −100…100.")
            return math.pow(left, right)
        value = visit(self.tree)
        if not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError("Le résultat doit être un nombre fini.")
        return value
