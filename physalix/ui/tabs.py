"""Onglets initiaux, prêts à recevoir les futures fonctionnalités."""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderTab(QWidget):
    """Présentation commune aux espaces encore vides."""

    def __init__(self, title: str, description: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(12)

        heading = QLabel(title)
        font = heading.font()
        font.setPointSize(20)
        font.setBold(True)
        heading.setFont(font)

        summary = QLabel(description)
        summary.setWordWrap(True)

        layout.addWidget(heading)
        layout.addWidget(summary)
        layout.addStretch()


class ModelingTab(PlaceholderTab):
    """Futur espace d'ajustement des modèles."""

    def __init__(self) -> None:
        super().__init__(
            "Modélisation",
            "Cet espace permettra de comparer vos mesures à des modèles mathématiques.",
        )
