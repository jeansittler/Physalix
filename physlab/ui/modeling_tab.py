"""Choisir une série, ajuster un modèle et consulter ses coefficients."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget, QTextBrowser, QFrame,
)

from physlab.fitting import MODELS, fit_model
from physlab.ui.fit_report import report_html, math_text, DETAILS_HTML
from physlab.ui.graph_tab import paired_values
from physlab.ui.components import page_layout, panel, label, role, ResponsiveCards
from physlab.ui.theme import report_stylesheet


class ReportView(QTextBrowser):
    """Un rapport sélectionnable intégré au défilement de l’onglet."""

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().setDefaultStyleSheet(report_stylesheet())
        self.document().documentLayout().documentSizeChanged.connect(self.fit_height)

    def fit_height(self, *args):
        self.setFixedHeight(max(100, int(self.document().size().height()) + 12))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.document().setTextWidth(self.viewport().width())
        self.fit_height()


class ModelingTab(QWidget):
    graph_requested = Signal()

    def __init__(self, graph):
        super().__init__()
        self.graph = graph
        layout = page_layout(QVBoxLayout(self))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        intro = QLabel("Modélisez les mesures d’une série avec une fonction de votre choix. Vous pouvez conserver plusieurs modélisations, sur l’ensemble des mesures ou sur des intervalles différents.")
        intro.setWordWrap(True)
        role(intro, "muted")
        body.addWidget(intro)
        model_panel, model_layout = panel("Modèle")
        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        model_layout.addLayout(form)
        self.series_choice = QComboBox()
        form.addRow("Série à modéliser", self.series_choice)
        fit_row = QHBoxLayout()
        self.fit_choice = QComboBox()
        self.new_fit_button = QPushButton("Ajouter une modélisation")
        self.new_fit_button.setToolTip("Créer une nouvelle modélisation sans modifier les précédentes, avec le même modèle ou un autre.")
        fit_row.addWidget(self.fit_choice, 1)
        fit_row.addWidget(self.new_fit_button)
        form.addRow("Modélisation", fit_row)
        self.model_choice = QComboBox()
        for key, (title, formula) in MODELS.items():
            self.model_choice.addItem(title, key)
        self.model_choice.setCurrentIndex(2)
        form.addRow("Modèle", self.model_choice)
        self.formula_label = QLabel()
        self.formula_label.setTextFormat(Qt.TextFormat.RichText)
        self.formula_label.setWordWrap(True)
        form.addRow("Expression", self.formula_label)
        self.expression = QLineEdit("a*x^2+b*x+c")
        self.initial = QLineEdit("a=1 ; b=0 ; c=0")
        self.custom_box = QWidget()
        custom_layout = QFormLayout(self.custom_box)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.addRow("Formule (membre droit)", self.expression)
        custom_layout.addRow("Paramètres et valeurs initiales", self.initial)
        self.custom_help = QLabel()
        self.custom_help.setTextFormat(Qt.TextFormat.PlainText)
        self.custom_help.setWordWrap(True)
        role(self.custom_help, "muted")
        custom_layout.addRow(self.custom_help)
        form.addRow(self.custom_box)
        interval_panel, interval_layout = panel("Intervalle et options")
        body.addWidget(ResponsiveCards(model_panel, interval_panel))
        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        interval_layout.addLayout(form)
        self.range_check = QCheckBox("Limiter la modélisation à un intervalle d’abscisses")
        form.addRow(self.range_check)
        range_row = QHBoxLayout()
        self.minimum, self.maximum = QLineEdit(), QLineEdit()
        self.minimum.setPlaceholderText("Minimum")
        self.maximum.setPlaceholderText("Maximum")
        self.select_button = QPushButton("Sélectionner sur le graphique")
        range_row.addWidget(self.minimum)
        range_row.addWidget(self.maximum)
        range_row.addWidget(self.select_button)
        form.addRow("Bornes incluses", range_row)
        self.extend_check = QCheckBox("Prolonger la droite sur le domaine des mesures")
        self.extend_check.setChecked(True)
        self.extend_check.setToolTip("Afficher la droite au-delà de l’intervalle utilisé pour le calcul, dans les limites des abscisses mesurées. Le prolongement en pointillés fins ne modifie pas les coefficients.")
        form.addRow(self.extend_check)
        actions = QHBoxLayout()
        self.fit_button = role(QPushButton("Calculer la modélisation"), "primary")
        self.remove_button = role(QPushButton("Retirer cette modélisation"), "danger")
        show = QPushButton("Voir le graphique")
        for button in (self.fit_button, self.remove_button, show):
            actions.addWidget(button)
        body.addLayout(actions)
        self.result_text = ReportView()
        body.addWidget(label("Résultats"))
        body.addWidget(self.result_text)
        self.details_button = QPushButton("Comprendre les indicateurs ▸")
        self.details_button.setCheckable(True)
        body.addWidget(self.details_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.details_text = ReportView()
        self.details_text.setHtml(DETAILS_HTML)
        self.details_text.hide()
        body.addWidget(self.details_text)
        self.details_button.toggled.connect(self.toggle_details)
        body.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.fit_choice.currentIndexChanged.connect(self.fit_selected)
        self.new_fit_button.clicked.connect(lambda: self.fit_choice.setCurrentIndex(0))
        self.extend_check.toggled.connect(self.extension_changed)
        self.fit_button.clicked.connect(self.calculate)
        self.remove_button.clicked.connect(self.remove_fit)
        show.clicked.connect(self.graph_requested)
        self.select_button.clicked.connect(self.select_interval)
        graph.calculate_interval_button.clicked.connect(self.calculate)
        graph.hide_interval_button.clicked.connect(lambda: graph.set_interval_editing(False))
        self.range_check.toggled.connect(self.range_toggled)
        graph.fit_region.sigRegionChanged.connect(self.read_region)
        self.minimum.editingFinished.connect(self.write_region)
        self.maximum.editingFinished.connect(self.write_region)
        self.series_choice.currentIndexChanged.connect(self.selection_changed)
        self.model_choice.currentIndexChanged.connect(self.update_formula)
        graph.changed.connect(self.sync_series)
        self.sync_series()
        self.range_toggled(False)
        self.update_formula()

    def current_series(self):
        number = self.series_choice.currentData()
        return next((s for s in self.graph.series if s.number == number), None)

    def sync_series(self):
        previous = self.series_choice.currentData()
        self.series_choice.blockSignals(True)
        self.series_choice.clear()
        for item in self.graph.series:
            if item.visible.isChecked():
                x, y = item.key()
                self.series_choice.addItem(
                    f"S{item.number} : {self.graph.axis_label(y)} en fonction de {self.graph.axis_label(x)}", item.number)
        index = self.series_choice.findData(previous)
        self.series_choice.setCurrentIndex(index if index >= 0 else 0)
        self.series_choice.blockSignals(False)
        if self.series_choice.currentData() != previous:
            self.selection_changed()
        else:
            self.sync_fits()
            self.update_formula()
            self.show_result()
        self.fit_button.setEnabled(self.current_series() is not None)

    def selection_changed(self, *args):
        self.range_check.setChecked(False)
        self.sync_fits(reset=True)
        self.fit_selected()

    def current_fit(self):
        item = self.current_series()
        number = self.fit_choice.currentData()
        return next((f for f in item.fits if f.number == number), None) if item else None

    def sync_fits(self, reset=False, selected=None):
        previous = selected if selected is not None else (None if reset else self.fit_choice.currentData())
        self.fit_choice.blockSignals(True)
        self.fit_choice.clear()
        self.fit_choice.addItem("Nouvelle modélisation", None)
        item = self.current_series()
        if item:
            for fit in item.fits:
                lo, hi = fit.result.x[0], fit.result.x[-1]
                self.fit_choice.addItem(
                    f"Modélisation {fit.number} · {MODELS.get(fit.kind, ('Modèle',))[0]} · [{lo:.5g} ; {hi:.5g}]".replace('.', ','), fit.number)
        index = self.fit_choice.findData(previous)
        self.fit_choice.setCurrentIndex(max(index, 0))
        self.fit_choice.blockSignals(False)
        self.fit_button.setText("Recalculer cette modélisation" if self.current_fit() else "Calculer la modélisation")

    def fit_selected(self, *args):
        self.graph.set_interval_editing(False)
        fit = self.current_fit()
        if fit:
            self.model_choice.setCurrentIndex(self.model_choice.findData(fit.kind))
            self.expression.setText(fit.settings.get('expression', ''))
            self.initial.setText(fit.settings.get('initial', ''))
            interval = fit.settings.get('interval')
            self.range_check.setChecked(interval is not None)
            if interval:
                self.graph.fit_region.setRegion(interval)
                self.read_region()
            self.extend_check.blockSignals(True)
            self.extend_check.setChecked(fit.settings.get('extend', False))
            self.extend_check.blockSignals(False)
        self.fit_button.setText("Recalculer cette modélisation" if fit else "Calculer la modélisation")
        self.update_formula()
        self.show_result()

    def extension_changed(self, enabled):
        fit = self.current_fit()
        if fit and fit.kind == 'affine':
            fit.settings['extend'] = enabled
            self.graph.draw_model(self.current_series(), fit)
            self.graph.fit_points()

    def update_formula(self, *args):
        kind = self.model_choice.currentData()
        self.custom_box.setVisible(kind == "custom")
        self.extend_check.setVisible(kind == "affine")
        self.formula_label.setText(math_text(MODELS[kind][1]) + (
            "   ·   x0 = première abscisse de l’intervalle (fixée)" if kind in
            ("charge", "discharge", "exponential", "sine") else ""))
        item = self.current_series()
        column = item.key()[0] if item else None
        name = self.graph.model.names[column] if column is not None and 0 <= column < self.graph.model.columnCount() else "x"
        self.custom_help.setText(
            f"x représente l’abscisse sélectionnée : {name}. Son nom peut aussi être utilisé s’il est un identifiant valide. "
            "Paramètres séparés par ; et décimales avec point ou virgule. "
            "Fonctions : sin, cos, tan, exp, log, log10, sqrt, abs ; constantes : pi, e. "
            "Les angles sont en radians. Exemple : A*exp(-x/tau)+c avec A=5 ; tau=1 ; c=0.")

    def range_toggled(self, enabled):
        for widget in (self.minimum, self.maximum, self.select_button):
            widget.setEnabled(enabled)
        self.graph.set_interval_editing(False)
        if enabled:
            item = self.current_series()
            if item:
                xs, _, _ = paired_values(self.graph.model.rows, *item.key())
                if xs:
                    low, high = min(xs), max(xs)
                    self.graph.fit_region.setRegion((low, high if high > low else low+1))
                    self.read_region()

    def read_region(self):
        low, high = self.graph.fit_region.getRegion()
        self.minimum.setText(format(low, ".12g"))
        self.maximum.setText(format(high, ".12g"))

    def interval(self):
        try:
            low, high = [float(w.text().replace(",", ".")) for w in (self.minimum, self.maximum)]
        except ValueError:
            raise ValueError("Saisissez deux bornes numériques pour l’intervalle.") from None
        from math import isfinite
        if not isfinite(low) or not isfinite(high) or low >= high:
            raise ValueError("La borne minimale doit être inférieure à la borne maximale.")
        return low, high

    def write_region(self):
        try:
            self.graph.fit_region.setRegion(self.interval())
        except ValueError:
            pass  # L’erreur sera explicitée au calcul, sans interrompre la saisie.

    def select_interval(self):
        if self.current_series() is None or not self.range_check.isChecked():
            return
        try:
            self.graph.fit_region.setRegion(self.interval())
        except ValueError as exc:
            self.result_text.setPlainText(str(exc))
            return
        self.graph.set_interval_editing(True)
        self.graph_requested.emit()

    def calculate(self):
        item = self.current_series()
        if item is None:
            return
        try:
            if any(column is None or not 0 <= column < self.graph.model.columnCount() for column in item.key()):
                raise ValueError("Choisissez une grandeur pour chaque axe du graphique.")
            xs, ys, skipped = paired_values(self.graph.model.rows, *item.key())
            result = fit_model(xs, ys, self.model_choice.currentData(),
                               expression=self.expression.text(), initial=self.initial.text(),
                               axis_name=self.graph.model.names[item.key()[0]],
                               interval=self.interval() if self.range_check.isChecked() else None)
        except (ValueError, ArithmeticError) as exc:
            self.result_text.setPlainText(f"Modélisation impossible : {exc}\n\nLe précédent modèle, s’il existe, est conservé sur le graphique.")
            self.graph.interval_hint.setText(f"Modélisation impossible : {exc} Modifiez l’intervalle ou les réglages dans Modélisation.")
            return
        settings = dict(expression=self.expression.text(), initial=self.initial.text(),
                        interval=self.interval() if self.range_check.isChecked() else None,
                        extend=self.model_choice.currentData() == 'affine' and self.extend_check.isChecked())
        fit = self.graph.set_model(item, result, self.model_choice.currentData(), settings, self.current_fit())
        self.sync_fits(selected=fit.number)
        self.show_result()
        self.graph.set_interval_editing(False)

    def remove_fit(self):
        self.graph.set_interval_editing(False)
        item = self.current_series()
        fit = self.current_fit()
        if item and fit:
            self.graph.clear_model(item, fit)
        self.sync_fits()
        self.show_result()

    def show_result(self):
        item = self.current_series()
        fit = self.current_fit()
        result = fit.result if fit else None
        self.remove_button.setEnabled(result is not None)
        self.details_button.setVisible(result is not None)
        if result is None:
            self.details_button.setChecked(False)
        if result is None:
            self.result_text.setPlainText("Choisissez un modèle puis cliquez sur Calculer la modélisation. Vous pouvez utiliser toutes les mesures ou limiter le calcul à un intervalle d’abscisses.\nLes modélisations déjà tracées sont conservées. Sélectionnez-en une dans la liste pour consulter ses résultats ou la recalculer.\nModifier les données, les unités ou les axes de la série retire ses modélisations devenues périmées.")
            return
        x, y = item.key()
        self.result_text.setHtml(report_html(
            result,
            f"Modélisation {fit.number} · S{item.number} — {self.graph.axis_label(y)} en fonction de {self.graph.axis_label(x)}",
            self.graph.axis_label(x), self.graph.model.names[y], self.graph.model.units[y]))

    def toggle_details(self, visible):
        self.details_text.setVisible(visible)
        self.details_button.setText("Comprendre les indicateurs ▾" if visible else "Comprendre les indicateurs ▸")
