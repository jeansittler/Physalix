"""Palette commune pour nommer simplement les grandeurs scientifiques."""

from PySide6.QtWidgets import QHBoxLayout, QMenu, QToolButton, QWidget

from physalix.ui.theme import LIGHT


SCIENTIFIC_SYMBOLS = ("α", "β", "γ", "Δ", "δ", "ε", "θ", "λ", "μ", "ρ", "σ", "φ", "ω")


def replace_name(field, symbol):
    """Remplacer le nom complet puis rendre le clavier au champ."""
    field.setText(symbol)
    field.setCursorPosition(len(symbol))
    field.setFocus()


def scientific_symbol_button(callback, parent=None):
    button = QToolButton(parent)
    button.setText("α…")
    button.setToolTip("Choisir un symbole scientifique ou grec")
    button.setAccessibleName("Choisir un symbole scientifique")
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    menu = QMenu(button)
    for symbol in SCIENTIFIC_SYMBOLS:
        menu.addAction(symbol, lambda checked=False, value=symbol: callback(value))
    button.setMenu(menu)
    return button


def scientific_symbol_field(field):
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(LIGHT.related)
    row.addWidget(field, 1)
    button = scientific_symbol_button(lambda symbol: replace_name(field, symbol), container)
    row.addWidget(button)
    return container, button
