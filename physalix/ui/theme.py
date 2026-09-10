"""Tokens et styles du thème clair, partagés par les widgets et les tracés."""

from dataclasses import dataclass
from physalix.ui.resources import resource_path

from PySide6.QtGui import QColor, QFont, QPalette


@dataclass(frozen=True)
class Theme:
    primary: str = "#168AFB"
    primary_hover: str = "#0E75D8"
    primary_pressed: str = "#095EB2"
    primary_soft: str = "#E1F0FF"
    selection: str = "#DCEEFF"
    background: str = "#EDF3F8"
    surface: str = "#FFFFFF"
    secondary: str = "#F5F8FB"
    text: str = "#10243E"
    muted: str = "#4E6073"
    text_disabled: str = "#7C8998"
    border: str = "#C8D5E2"
    border_strong: str = "#A9BBCD"
    subtle: str = "#E2EAF1"
    disabled: str = "#DDE5EC"
    success: str = "#238554"
    warning: str = "#A85D00"
    error: str = "#B42318"
    video: str = "#151922"
    video_text: str = "#D7DCE5"
    font: str = "Segoe UI"
    font_px: int = 13
    title_px: int = 22
    section_title_px: int = 17
    card_title_px: int = 15
    caption_px: int = 12
    radius: int = 6
    card_radius: int = 8
    control_height: int = 32
    button_height: int = 32
    wide_layout: int = 1480
    small: int = 4
    related: int = 8
    group: int = 12
    section: int = 16
    page: int = 24


LIGHT = Theme()
SERIES_COLORS = (LIGHT.primary, "#d84315", "#2e7d32", "#7b1fa2", "#00838f", "#ad1457")


def report_stylesheet(t=LIGHT):
    return (f"body {{ color: {t.text}; font-family: '{t.font}'; font-size: {t.font_px}px; }}"
            "h2 { font-size: 17px; margin-top: 4px; margin-bottom: 8px; }"
            "h3 { font-size: 15px; margin-top: 16px; margin-bottom: 8px; }"
            "p { margin-top: 6px; margin-bottom: 10px; }"
            "td { vertical-align: middle; }"
            ".metric { font-size: 18px; } .equation { font-size: 20px; }")


def stylesheet(t=LIGHT):
    assets = resource_path().as_posix()
    return f"""
    QWidget {{ color: {t.text}; font-family: '{t.font}'; font-size: {t.font_px}px; }}
    QMainWindow, QDialog, QTabWidget::pane, QScrollArea > QWidget > QWidget {{ background: {t.background}; }}
    QTabWidget::pane {{ border: 0; border-top: 1px solid {t.border_strong}; }}
    QTabWidget#mainNavigation QTabBar {{ background: {t.surface}; }}
    QTabBar::tab {{ background: {t.surface}; color: {t.muted}; border: 1px solid transparent;
        border-radius: {t.radius}px; padding: 11px 16px; margin: 9px 3px; font-weight: 600; }}
    QTabBar::tab:hover {{ background: {t.primary_soft}; color: {t.text}; border-color: {t.border}; }}
    QTabBar::tab:selected {{ background: {t.primary}; color: white; }}
    QTabBar::tab:focus {{ border: 2px solid {t.primary_pressed}; }}
    QWidget[role="brand"] {{ background: {t.surface}; border-right: 1px solid {t.border}; }}
    QLabel[role="brandTitle"] {{ font-size: {t.title_px}px; font-weight: 700; }}
    QLabel[role="sectionTitle"] {{ font-size: {t.section_title_px}px; font-weight: 650; }}
    QLabel[role="cardTitle"] {{ font-size: {t.card_title_px}px; font-weight: 650; }}
    QLabel[role="muted"], QLabel[role="caption"] {{ color: {t.muted}; font-size: {t.caption_px}px; }}
    QLabel[role="caption"] {{ font-weight: 600; }}
    QLabel[role="cellAddress"] {{ background: {t.secondary}; border: 1px solid {t.border};
        border-radius: {t.radius}px; padding: 6px 10px; font-weight: 650; }}
    QLabel[role="formulaMark"] {{ color: {t.primary_pressed}; font-size: {t.card_title_px}px; font-weight: 700; }}
    QLabel[role="error"] {{ color: {t.error}; }}
    QLabel[role="success"] {{ color: {t.success}; }}
    QFrame[role="panel"], QFrame[role="card"], QWidget[role="panel"], QWidget[role="card"], QTextBrowser {{ background: {t.surface};
        border: 1px solid {t.border}; border-radius: {t.card_radius}px; }}
    QGroupBox {{ background: {t.surface}; border: 1px solid {t.border};
        border-radius: {t.card_radius}px; margin-top: 12px; padding: 20px 12px 12px;
        font-size: {t.card_title_px}px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 16px; padding: 0 6px;
        color: {t.text}; background: {t.surface}; }}
    QPushButton, QToolButton {{ background: {t.surface}; border: 1px solid {t.border_strong};
        border-radius: {t.radius}px; padding: 6px 12px; min-height: 18px; }}
    QPushButton:hover, QToolButton:hover {{ background: {t.primary_soft}; border-color: {t.primary}; }}
    QPushButton:pressed, QToolButton:pressed {{ background: {t.selection}; }}
    QPushButton:focus, QToolButton:focus {{ border: 2px solid {t.primary}; padding: 5px 11px; }}
    QPushButton[role="primary"] {{ background: {t.primary}; border-color: {t.primary}; color: white; font-weight: 600; }}
    QPushButton[role="primary"]:hover {{ background: {t.primary_hover}; border-color: {t.primary_hover}; }}
    QPushButton[role="primary"]:pressed {{ background: {t.primary_pressed}; }}
    QPushButton[role="quiet"] {{ color: {t.muted}; border-color: {t.border}; background: transparent; }}
    QPushButton[role="danger"] {{ color: {t.error}; border-color: {t.border}; background: transparent; }}
    QPushButton[role="danger"]:hover {{ color: {t.error}; border-color: {t.error}; background: #FFF1F0; }}
    QPushButton:disabled, QPushButton[role="primary"]:disabled, QToolButton:disabled {{
        background: {t.disabled}; color: {t.text_disabled}; border-color: {t.disabled}; font-weight: 400; }}
    QLineEdit, QComboBox, QAbstractSpinBox {{ background: {t.surface}; border: 1px solid {t.border};
        border-radius: {t.radius}px; padding: 6px 8px; min-height: 18px;
        selection-background-color: {t.selection}; selection-color: {t.text}; }}
    QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover {{ border-color: {t.border_strong}; }}
    QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {{ border: 2px solid {t.primary}; padding: 5px 7px; }}
    QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled {{ background: {t.disabled}; color: {t.text_disabled}; border-color: {t.disabled}; }}
    QComboBox::drop-down {{ border: 0; width: 24px; }}
    QComboBox::down-arrow {{ image: url("{assets}/chevron-down.svg"); width: 16px; height: 16px; }}
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 20px; border: 0; }}
    QAbstractSpinBox::up-arrow {{ image: url("{assets}/chevron-up.svg"); width: 12px; height: 12px; }}
    QAbstractSpinBox::down-arrow {{ image: url("{assets}/chevron-down.svg"); width: 12px; height: 12px; }}
    QTabBar QToolButton {{ padding: 0; width: 24px; border-radius: 0; }}
    QTabBar QToolButton::left-arrow {{ image: url("{assets}/chevron-left.svg"); }}
    QTabBar QToolButton::right-arrow {{ image: url("{assets}/chevron-right.svg"); }}
    QComboBox {{ padding-right: 26px; }}
    QComboBox QAbstractItemView {{ background: {t.surface}; selection-background-color: {t.selection};
        selection-color: {t.text}; border: 1px solid {t.border}; padding: 4px; }}
    QCheckBox {{ spacing: 8px; padding: 4px 0; }}
    QCheckBox:disabled {{ color: {t.text_disabled}; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; background: {t.surface}; border: 1px solid {t.border_strong}; border-radius: 4px; }}
    QCheckBox::indicator:checked {{ background: {t.primary}; border-color: {t.primary}; image: url("{assets}/check.svg"); }}
    QCheckBox::indicator:hover, QCheckBox::indicator:focus {{ border-color: {t.primary}; }}
    QCheckBox::indicator:disabled {{ background: {t.disabled}; border-color: {t.disabled}; }}
    QCheckBox::indicator:checked:disabled {{ background: {t.text_disabled}; }}
    QTableView {{ background: {t.surface}; alternate-background-color: {t.secondary};
        gridline-color: {t.border}; border: 1px solid {t.border_strong}; border-radius: {t.radius}px;
        selection-background-color: {t.selection}; selection-color: {t.text}; }}
    QTableView::item {{ padding: 4px 8px; border: 0; }}
    QTableView::item:hover {{ background: {t.primary_soft}; }}
    QTableView::item:selected {{ background: {t.selection}; color: {t.text}; border: 1px solid {t.primary}; }}
    QHeaderView::section {{ background: {t.secondary}; color: {t.text}; padding: 7px 10px;
        border: 0; border-right: 1px solid {t.border}; border-bottom: 1px solid {t.border}; font-weight: 600; }}
    QTableCornerButton::section {{ background: {t.secondary}; border: 0; }}
    QTableView QLineEdit, QTableView QComboBox {{ min-height: 0; padding: 0 4px; border-radius: 0; }}
    QScrollArea {{ border: 0; background: transparent; }}
    QScrollBar:vertical {{ background: {t.secondary}; width: 12px; margin: 0; }}
    QScrollBar:horizontal {{ background: {t.secondary}; height: 12px; margin: 0; }}
    QScrollBar::handle {{ background: {t.border_strong}; border: 3px solid {t.secondary}; border-radius: 5px; min-width: 24px; min-height: 24px; }}
    QScrollBar::handle:hover {{ background: {t.muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.primary}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: 14px; margin: -5px 0; background: {t.primary}; border-radius: 7px; }}
    QSlider::handle:horizontal:disabled {{ background: {t.disabled}; }}
    QMenu {{ background: {t.surface}; border: 1px solid {t.border}; padding: 4px; }}
    QMenu::item {{ padding: 7px 24px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {t.selection}; }}
    QMenu::item:disabled {{ color: {t.muted}; }}
    QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 6px; }}
    QStatusBar {{ background: {t.secondary}; color: {t.muted}; border-top: 1px solid {t.border}; }}
    QStatusBar::item {{ border: 0; }}
    QTextBrowser {{ padding: 12px; selection-background-color: {t.selection}; selection-color: {t.text}; }}
    QTextBrowser[role="report"] {{ background: transparent; border: 0; border-radius: 0; padding: 4px 0; }}
    QTextBrowser[status="error"] {{ color: {t.error}; }}
    """


def apply_theme(app):
    """Une palette explicite évite d'hériter du thème sombre de Windows."""
    app.setStyle("Fusion")
    font = QFont(LIGHT.font)
    font.setPixelSize(LIGHT.font_px)
    app.setFont(font)
    palette = QPalette()
    for role, color in ((QPalette.Window, LIGHT.background), (QPalette.WindowText, LIGHT.text),
                        (QPalette.Base, LIGHT.surface), (QPalette.AlternateBase, LIGHT.secondary),
                        (QPalette.Text, LIGHT.text), (QPalette.Button, LIGHT.surface),
                        (QPalette.ButtonText, LIGHT.text), (QPalette.Highlight, LIGHT.primary),
                        (QPalette.HighlightedText, LIGHT.surface), (QPalette.PlaceholderText, LIGHT.muted)):
        palette.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        palette.setColor(QPalette.Disabled, role, QColor(LIGHT.muted))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet())
