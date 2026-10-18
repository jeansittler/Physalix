"""Écran de démarrage compact affiché avant les imports lourds de Physalyx."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QProgressBar, QSplashScreen, QVBoxLayout

from physalix.ui.branding import BrandLogo


class StartupSplash(QSplashScreen):
    def __init__(self):
        canvas = QPixmap(520, 250)
        canvas.fill(Qt.GlobalColor.white)
        super().__init__(canvas, Qt.WindowType.FramelessWindowHint)
        self.setObjectName("startupSplash")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(42, 30, 42, 28)
        layout.setSpacing(10)

        self.brand_logo = BrandLogo()
        self.brand_logo.setDisplaySize(270, 86)
        layout.addWidget(self.brand_logo, 0, Qt.AlignmentFlag.AlignCenter)

        self.message_label = QLabel("Initialisation de Physalyx…")
        self.message_label.setObjectName("startupMessage")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message_label)

        self.activity = QProgressBar()
        self.activity.setObjectName("startupActivity")
        self.activity.setRange(0, 0)
        self.activity.setTextVisible(False)
        self.activity.setFixedHeight(5)
        layout.addWidget(self.activity)

        self.setStyleSheet(
            "QSplashScreen#startupSplash { background: #FFFFFF; border: 1px solid #A9BBCD; }"
            "QLabel { color: #10243E; font-family: 'Segoe UI'; }"
            "QLabel#startupMessage { color: #43566A; font-size: 12px; }"
            "QProgressBar#startupActivity { border: 0; background: #E2EAF1; }"
            "QProgressBar#startupActivity::chunk { background: #168AFB; }"
        )

    def set_stage(self, message):
        self.message_label.setText(message)
