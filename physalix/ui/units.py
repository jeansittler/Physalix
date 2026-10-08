"""Suggestions d'unités ; la saisie reste entièrement libre."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter
from physalix.ui.components import WheelSafeComboBox

# Cette liste aide à la saisie, sans imposer de catalogue ni de conversion.
COMMON_UNITS = (
    "", "Sans unité", "%",
    "s", "ms", "µs", "ns", "min", "h",
    "m", "km", "cm", "mm", "µm", "nm", "m²", "cm²", "mm²",
    "m³", "dm³", "cm³", "L", "mL", "µL",
    "kg", "g", "mg", "µg", "mol", "mmol", "µmol",
    "mol/L", "mmol/L", "mol/m³", "g/L", "mg/L", "kg/m³", "g/cm³", "g/mol",
    "°C", "K", "Pa", "hPa", "kPa", "bar", "atm",
    "m/s", "km/h", "m/s²", "N", "mN", "N/kg", "N/m", "N·m",
    "J", "kJ", "mJ", "eV", "W", "mW", "kW", "Wh", "kWh",
    "J/K", "J/(kg·K)", "J/mol", "kJ/mol",
    "A", "mA", "µA", "V", "mV", "kV", "Ω", "kΩ", "MΩ",
    "S", "mS", "µS", "S/m", "mS/cm", "µS/cm",
    "C", "F", "µF", "nF", "pF", "H", "mH", "T", "mT", "Wb",
    "Hz", "kHz", "MHz", "rad", "°", "rad/s", "dB", "lx", "cd",
    "m⁻¹", "s⁻¹", "L/(mol·cm)", "mol/(L·s)", "Bq",
)


def unit_combo(parent=None):
    """Créer le sélecteur éditable commun au tableur et aux outils d'acquisition."""
    editor = WheelSafeComboBox(parent)
    editor.setEditable(True)
    editor.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    editor.addItems(COMMON_UNITS)
    editor.setMaxVisibleItems(12)
    editor.lineEdit().setPlaceholderText("Choisir ou saisir une unité")
    editor.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    editor.completer().setFilterMode(Qt.MatchFlag.MatchContains)
    editor.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseSensitive)
    editor.lineEdit().setTextMargins(2, 0, 2, 0)
    editor.lineEdit().setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return editor
