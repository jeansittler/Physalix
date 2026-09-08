"""Aide commune aux formules de colonnes et de cellules."""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPushButton, QTextBrowser, QVBoxLayout


class MathHelpDialog(QDialog):
    def __init__(self, parent=None, spreadsheet=False):
        super().__init__(parent)
        self.setWindowTitle("Fonctions usuelles et puissances de 10")
        self.resize(580, 480)
        layout = QVBoxLayout(self)
        text = QTextBrowser()
        reference = ("Commencez une formule par <b>=</b> : <b>=ln(A1)</b>, <b>=8E5*A1</b>. "
                     "A1 désigne la première mesure de A. La recopie adapte A1 en A2, A3… ; "
                     "$A$1 reste fixe. Une valeur seule, comme <b>8E5</b>, ne nécessite pas =."
                     if spreadsheet else
                     "Utilisez les noms des grandeurs ou C1, C2… : <b>ln(C1)</b>, <b>8E5*C1</b>. "
                     "Ne mettez pas de signe = au début. Les noms des grandeurs sont sensibles à la casse.")
        text.setHtml("<h3>Écriture scientifique</h3>"
                     "<b>8E5 = 8 × 10⁵ = 800 000</b><br>"
                     "<b>2,5E-3 = 2,5 × 10⁻³ = 0,0025</b><br>"
                     "Écrivez sans espaces : 8E5 ou 8e5 ; 8E+5 est aussi accepté."
                     "<h3>Fonctions à un argument</h3>"
                     "<table cellpadding='5'>"
                     "<tr><td><b>ln(x)</b></td><td>Logarithme népérien ; ln(e) = 1</td></tr>"
                     "<tr><td><b>log(x)</b></td><td>Logarithme en base 10 ; log(100) = 2</td></tr>"
                     "<tr><td><b>exp(x)</b></td><td>Exponentielle eˣ ; exp(0) = 1</td></tr>"
                     "<tr><td><b>sqrt(x), racine(x)</b></td><td>Racine carrée</td></tr>"
                     "<tr><td><b>abs(x)</b></td><td>Valeur absolue</td></tr>"
                     "<tr><td><b>sin(x), cos(x), tan(x)</b></td><td>Angles en radians</td></tr></table>"
                     "<p>Majuscules et minuscules sont acceptées pour les fonctions. "
                     "<b>log10</b> est un autre nom de <b>log</b>. "
                     "ln et log demandent x &gt; 0 ; sqrt demande x ≥ 0.</p>"
                     "<h3>Opérations et références</h3>"
                     "Puissance : <b>10^5</b>, <b>x^2</b> ou <b>x²</b>. "
                     "Opérations : +, −, *, / ; parenthèses (…). "
                     "Constantes : <b>pi</b> et <b>e</b>. Décimales : virgule ou point."
                     "<p>" + reference + "</p>"
                     "<p>Utilisez des unités cohérentes : aucune conversion automatique.</p>")
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Fermer")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def math_help_button(parent, spreadsheet=False):
    button = QPushButton("Fonctions usuelles…", parent)
    button.setToolTip("Aide : ln, log, exp, puissances et notation scientifique 8E5")
    button.clicked.connect(lambda: MathHelpDialog(parent, spreadsheet).exec())
    return button
