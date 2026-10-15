"""Écran de démarrage compact affiché avant les imports lourds de Physalix."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QProgressBar, QSplashScreen, QVBoxLayout

from physalix.ui.resources import resource_path


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

        source = QPixmap(str(resource_path("branding", "logo_physalix.png")))
        logo = source.copy(QRect(211, 70, 1750, 549)).scaled(
            270,
            86,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.logo_label = QLabel()
        self.logo_label.setPixmap(logo)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.logo_label)

        self.title_label = QLabel("Physalix")
        self.title_label.setObjectName("startupTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        self.message_label = QLabel("Initialisation de Physalix…")
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
            "QLabel#startupTitle { font-size: 22px; font-weight: 700; }"
            "QLabel#startupMessage { color: #43566A; font-size: 12px; }"
            "QProgressBar#startupActivity { border: 0; background: #E2EAF1; }"
            "QProgressBar#startupActivity::chunk { background: #168AFB; }"
        )

    def set_stage(self, message):
        self.message_label.setText(message)
