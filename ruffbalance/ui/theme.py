"""Color tokens and stylesheets, ported from the original app's CSS custom
properties. Two palettes (light / dark); "auto" picks by the OS palette."""
from __future__ import annotations

LIGHT = {
    "canvas": "#E9EDF1", "surface": "#FFFFFF", "surface2": "#F4F6F9", "surface3": "#E4E9EF",
    "line": "#CFD7E0", "lineSoft": "#E3E9EF", "lineStrong": "#AEBBC8",
    "text": "#16202B", "muted": "#5E6E7E", "faint": "#8A99A8",
    "accent": "#2B4C7E", "accentSoft": "#DCE6F4", "accentText": "#FFFFFF",
    "credit": "#0F6B4F", "debit": "#9B2C2C", "flag": "#8A6D1F", "flagSoft": "#F6EEDA",
    "rowAlt": "#F7F9FB", "rowHover": "#EDF3FA", "rowSel": "#D9E6F7",
    "manualDue": "#8A6D00",
}
DARK = {
    "canvas": "#0F141A", "surface": "#171D25", "surface2": "#1C232C", "surface3": "#242D38",
    "line": "#2C3743", "lineSoft": "#232C36", "lineStrong": "#3D4A58",
    "text": "#E4EAF0", "muted": "#98A6B4", "faint": "#6E7D8C",
    "accent": "#6E9BD6", "accentSoft": "#22364F", "accentText": "#0C1219",
    "credit": "#53B98F", "debit": "#E0837A", "flag": "#D8B45E", "flagSoft": "#2E2818",
    "rowAlt": "#1B222B", "rowHover": "#212C38", "rowSel": "#26384F",
    "manualDue": "#E8C468",
}


def palette_for(theme: str) -> dict:
    if theme == "dark":
        return DARK
    if theme == "light":
        return LIGHT
    # "auto" -- ask Qt's own palette whether we're in a dark window
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            win_color = app.palette().window().color()
            if win_color.lightness() < 128:
                return DARK
    except Exception:
        pass
    return LIGHT


def stylesheet(theme: str) -> str:
    c = palette_for(theme)
    return f"""
    QWidget {{ background: {c['canvas']}; color: {c['text']}; font-size: 13px; }}
    QMainWindow {{ background: {c['canvas']}; }}
    #Sidebar {{ background: {c['surface2']}; border-right: 1px solid {c['line']}; }}
    #Topbar {{ background: {c['surface']}; border-bottom: 1px solid {c['line']}; }}
    #Content {{ background: {c['canvas']}; }}
    QLabel#Brand {{ font-size: 16px; font-weight: 600; }}
    QLabel#NetWorthLabel {{ color: {c['muted']}; font-size: 11px; }}
    QLabel#NetWorthValue {{ font-size: 22px; font-weight: 600; font-family: "IBM Plex Mono", monospace; }}
    QLabel.neg {{ color: {c['debit']}; }}
    QLabel.pos {{ color: {c['credit']}; }}
    QLabel.dim {{ color: {c['muted']}; }}
    QLabel.tiny {{ color: {c['muted']}; font-size: 11px; }}
    QLabel.money {{ font-family: "IBM Plex Mono", monospace; }}
    QListWidget#NavList {{ border: none; background: transparent; }}
    QListWidget#NavList::item {{ padding: 6px 8px; border-radius: 4px; }}
    QListWidget#NavList::item:selected {{ background: {c['accent']}; color: {c['accentText']}; }}
    QListWidget#NavList::item:hover:!selected {{ background: {c['surface3']}; }}
    QListWidget#AcctList {{ border: none; background: transparent; }}
    QListWidget#AcctList::item {{ padding: 5px 8px; border-radius: 4px; }}
    QListWidget#AcctList::item:selected {{ background: {c['accent']}; color: {c['accentText']}; }}
    QListWidget#AcctList::item:hover:!selected {{ background: {c['surface3']}; }}
    QFrame.panel {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 6px; }}
    QLabel.panelTitle {{ font-weight: 600; font-size: 13px; }}
    QPushButton {{ padding: 5px 10px; border: 1px solid {c['line']}; border-radius: 4px; background: {c['surface']}; }}
    QPushButton:hover {{ background: {c['surface2']}; border-color: {c['lineStrong']}; }}
    QPushButton:disabled {{ color: {c['faint']}; }}
    QPushButton#Primary {{ background: {c['accent']}; color: {c['accentText']}; border-color: {c['accent']}; font-weight: 600; }}
    QPushButton#Danger {{ color: {c['debit']}; }}
    QPushButton#Ghost {{ border-color: transparent; background: transparent; }}
    QPushButton:checkable:checked {{ background: {c['accent']}; color: {c['accentText']}; border-color: {c['accent']}; }}
    QLineEdit, QComboBox, QTextEdit, QDateEdit, QSpinBox, QDoubleSpinBox {{
        border: 1px solid {c['line']}; border-radius: 4px; padding: 4px 6px; background: {c['surface']}; color: {c['text']};
    }}
    QTableWidget {{ background: {c['surface']}; gridline-color: {c['lineSoft']}; border: 1px solid {c['line']}; }}
    QHeaderView::section {{
        background: {c['surface2']}; color: {c['muted']}; padding: 5px 6px; border: none;
        border-right: 1px solid {c['line']}; border-bottom: 1px solid {c['line']}; font-weight: 600; font-size: 11px;
    }}
    QTableWidget::item:selected {{ background: {c['rowSel']}; color: {c['text']}; }}
    QTableCornerButton::section {{ background: {c['surface2']}; border: none; }}
    QScrollArea {{ border: none; }}
    QTabWidget::pane {{ border: 1px solid {c['line']}; }}
    QTabBar::tab {{ padding: 6px 12px; }}
    QTabBar::tab:selected {{ background: {c['accentSoft']}; }}
    """


def qcolor(c: dict, key: str):
    from PySide6.QtGui import QColor
    return QColor(c[key])
