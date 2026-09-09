"""Création de dérivées et de colonnes calculées depuis les mesures."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QDialog, QDialogButtonBox, QMenu,
)

from physalix.calculations import CalculationEngine, derivative_unit
from physalix.ui.math_help import math_help_button
from physalix.ui.components import page_layout, role, ResponsiveCards, label as section_label


class FormulaEditDialog(QDialog):
    """Modifier le calcul en place ; Annuler conserve intégralement la grandeur."""

    def __init__(self, engine, item, parent=None):
        super().__init__(parent)
        self.engine, self.item = engine, item
        self.setWindowTitle("Modifier la formule")
        self.resize(600, 280)
        layout = page_layout(QVBoxLayout(self))
        title = section_label(f"Formule de {engine.model.names[item.column]}")
        title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(title)
        self.expression = QLineEdit(item.formula.editable_expression())
        caption = QLabel("Formule :")
        caption.setBuddy(self.expression)
        layout.addWidget(caption)
        layout.addWidget(self.expression)
        layout.addWidget(math_help_button(self))
        columns = QComboBox()
        for column, name in enumerate(engine.model.names):
            columns.addItem(f"C{column + 1} · {name}", column)
        insert = QPushButton("Insérer la grandeur")
        insert.clicked.connect(lambda: self.expression.insert(f"C{columns.currentData() + 1}"))
        row = QHBoxLayout()
        row.addWidget(columns, 1)
        row.addWidget(insert)
        layout.addLayout(row)
        layout.addWidget(section_label(
            "C1, C2… désignent les colonnes actuelles. Vous pouvez aussi saisir leurs noms. "
            "Les grandeurs qui dépendent de ce calcul seront mises à jour.", "muted"))
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        role(buttons.button(QDialogButtonBox.StandardButton.Save), "primary").setText("Enregistrer")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.expression.setFocus()

    def save(self):
        try:
            if not any(item is self.item for item in self.engine.items):
                raise ValueError("Cette grandeur a été supprimée.")
            self.engine.update_formula(self.item.column, self.expression.text())
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.accept()


class CalculationsTab(QWidget):
    def __init__(self, model):
        super().__init__()
        self.model = model
        self.engine = CalculationEngine(model)
        outer = page_layout(QVBoxLayout(self))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        intro = QLabel("Créez une grandeur calculée, disponible dans Données et Graphique. "
                       "Les résultats se mettent à jour avec les mesures ; les noms et unités restent modifiables dans Données.")
        intro.setWordWrap(True)
        role(intro, "muted")
        layout.addWidget(intro)

        derivative = QGroupBox("Dérivée centrée")
        form = QFormLayout(derivative)
        form.setVerticalSpacing(12)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.source = QComboBox()
        self.axis = QComboBox()
        self.derivative_name = QLineEdit()
        self.derivative_name.setPlaceholderText("Exemple : Vx, Vy ou ax")
        self.derivative_unit = QLineEdit()
        form.addRow("Grandeur à dériver :", self.source)
        form.addRow("Par rapport à :", self.axis)
        form.addRow("Nom du résultat :", self.derivative_name)
        form.addRow("Unité du résultat :", self.derivative_unit)
        rule = QLabel("Dᵢ = (fᵢ₊₁ − fᵢ₋₁) / (uᵢ₊₁ − uᵢ₋₁)\n"
                      "Premier et dernier points : vides. Aucun calcul à travers une donnée manquante. "
                      "Avec un pas variable, cette formule donne la pente entre les deux voisins.")
        rule.setWordWrap(True)
        role(rule, "muted")
        form.addRow(rule)
        self.derive_button = role(QPushButton("Créer la dérivée"), "primary")
        self.derive_button.clicked.connect(self.create_derivative)
        form.addRow(self.derive_button)

        formula = QGroupBox("Nouvelle grandeur par formule")
        form = QFormLayout(formula)
        form.setVerticalSpacing(12)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.formula_name = QLineEdit()
        self.formula_name.setPlaceholderText("Exemple : v")
        self.formula_unit = QLineEdit()
        self.formula_unit.setPlaceholderText("Exemple : cm/s si Vx et Vy sont en cm/s")
        self.expression = QLineEdit()
        self.expression.setPlaceholderText("SQRT(Vx^2 + Vy^2)")
        self.expression.returnPressed.connect(self.create_formula)
        form.addRow("Nom du résultat :", self.formula_name)
        form.addRow("Unité du résultat :", self.formula_unit)
        form.addRow("Formule :", self.expression)
        insert_row = QHBoxLayout()
        self.quantity = QComboBox()
        insert_row.addWidget(self.quantity, 1)
        insert = QPushButton("Insérer la grandeur")
        insert.clicked.connect(self.insert_quantity)
        insert_row.addWidget(insert)
        form.addRow(insert_row)
        keys = QHBoxLayout()
        for label, value in (("SQRT(…)", "SQRT("), ("²", "²"), ("^", "^"),
                             ("(", "("), (")", ")"), ("+", "+"), ("−", "-"), ("×", "*"), ("/", "/")):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, text=value: self.insert_text(text))
            keys.addWidget(button)
        form.addRow(keys)
        form.addRow(math_help_button(self))
        self.formula_button = role(QPushButton("Créer la grandeur"), "primary")
        self.formula_button.clicked.connect(self.create_formula)
        form.addRow(self.formula_button)
        layout.addWidget(ResponsiveCards(derivative, formula))
        self.feedback = QLabel("Les cellules calculées sont protégées ; renommez leur en-tête dans Données à tout moment.")
        self.feedback.setWordWrap(True)
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.feedback)
        role(self.feedback, "muted")
        layout.addWidget(section_label("Grandeurs calculées"))
        layout.addWidget(section_label("Double-cliquez sur une grandeur par formule pour modifier son calcul.", "muted"))
        self.history = QTableWidget(0, 4)
        self.history.setHorizontalHeaderLabels(["Grandeur", "Unité", "Calcul lié", "Bilan"])
        self.history.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history.cellDoubleClicked.connect(self.edit_formula)
        self.history.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history.customContextMenuRequested.connect(self.formula_menu)
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.history.horizontalHeader().setStretchLastSection(True)
        self.history.setMinimumHeight(150)
        self.history.verticalHeader().setDefaultSectionSize(32)
        layout.addWidget(self.history)
        self.edit_formula_button = QPushButton("Modifier la formule…")
        self.edit_formula_button.clicked.connect(lambda: self.edit_formula(self.history.currentRow()))
        self.history.itemSelectionChanged.connect(self.update_edit_button)
        self.edit_formula_button.setEnabled(False)
        layout.addWidget(self.edit_formula_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        self.engine.changed.connect(self.refresh)
        self.source.currentIndexChanged.connect(self.suggest_derivative)
        self.axis.currentIndexChanged.connect(self.suggest_derivative)
        self.refresh()
        time_column = next((i for i, name in enumerate(model.names) if name == "t"), min(1, model.columnCount() - 1))
        self.axis.setCurrentIndex(time_column)
        self.suggest_derivative()

    def refresh(self):
        for combo in (self.source, self.axis, self.quantity):
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for i, (name, unit) in enumerate(zip(self.model.names, self.model.units)):
                combo.addItem(f"C{i + 1} · {name}" + (f" ({unit})" if unit else ""), i)
            combo.setCurrentIndex(max(0, combo.findData(previous)))
            combo.blockSignals(False)
        self.history.setRowCount(len(self.engine.items))
        for row, item in enumerate(self.engine.items):
            description = (item.formula.description(self.model.names) if item.formula else
                           f"d({self.model.names[item.source]}) / d({self.model.names[item.axis]}) · centrée")
            for col, text in enumerate((self.model.names[item.column], self.model.units[item.column], description, item.status)):
                cell = QTableWidgetItem(text)
                cell.setToolTip(text)
                self.history.setItem(row, col, cell)
        self.update_edit_button()

    def formula_at(self, row):
        if 0 <= row < len(self.engine.items):
            item = self.engine.items[row]
            if item.formula is not None:
                return item
        return None

    def update_edit_button(self):
        self.edit_formula_button.setEnabled(self.formula_at(self.history.currentRow()) is not None)

    def edit_formula(self, row, column=0):
        item = self.formula_at(row)
        if item is not None:
            dialog = FormulaEditDialog(self.engine, item, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.feedback.setText(f"Formule de {self.model.names[item.column]} modifiée. Les résultats ont été recalculés.")

    def formula_menu(self, position):
        row = self.history.rowAt(position.y())
        if self.formula_at(row) is None:
            return
        self.history.selectRow(row)
        menu = QMenu(self)
        menu.addAction("Modifier la formule…", lambda: self.edit_formula(row))
        menu.exec(self.history.viewport().mapToGlobal(position))

    def suggest_derivative(self):
        source, axis = self.source.currentData(), self.axis.currentData()
        if source is None or axis is None:
            return
        self.derivative_name.setText(f"d{self.model.names[source]}_d{self.model.names[axis]}")
        self.derivative_unit.setText(derivative_unit(self.model.units[source], self.model.units[axis]))

    def insert_text(self, text):
        self.expression.insert(text)
        self.expression.setFocus()

    def insert_quantity(self):
        column = self.quantity.currentData()
        if column is not None:
            self.insert_text(f"C{column + 1}")

    def create_derivative(self):
        self._create(self.derivative_name.text(), self.derivative_unit.text(),
                     source=self.source.currentData(), axis=self.axis.currentData())

    def create_formula(self):
        self._create(self.formula_name.text(), self.formula_unit.text(), expression=self.expression.text())

    def _create(self, name, unit, **definition):
        try:
            column = self.engine.add(name, unit, **definition)
        except ValueError as error:
            self.feedback.setText(str(error))
            return
        self.feedback.setText(f"{self.model.names[column]} créée dans Données (C{column + 1}). "
                              "Vous pouvez y modifier son nom et son unité. " + self.engine.items[-1].status)
