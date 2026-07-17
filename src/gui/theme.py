"""Temas visuais da aplicação (QSS).

Paleta inspirada no Discord: fundos em tons de cinza-azulado escuro,
destaque em roxo/azul (#5865F2) e cantos arredondados.
"""
from __future__ import annotations

# Paleta "dark" (Discord-like).
DARK = {
    "bg_darkest": "#1e1f22",   # sidebar
    "bg_dark": "#2b2d31",      # painéis
    "bg_mid": "#313338",       # área principal
    "bg_light": "#383a40",     # inputs / cards
    "bg_hover": "#404249",
    "accent": "#5865f2",       # blurple
    "accent_hover": "#4752c4",
    "success": "#23a55a",
    "warning": "#f0b232",
    "danger": "#f23f43",
    "text": "#f2f3f5",
    "text_muted": "#949ba4",
    "border": "#26272b",
}

# Paleta "light" (tema alternativo).
LIGHT = {
    "bg_darkest": "#e3e5e8",
    "bg_dark": "#f2f3f5",
    "bg_mid": "#ffffff",
    "bg_light": "#ebedef",
    "bg_hover": "#d7d9dc",
    "accent": "#5865f2",
    "accent_hover": "#4752c4",
    "success": "#23a55a",
    "warning": "#f0b232",
    "danger": "#f23f43",
    "text": "#2e3338",
    "text_muted": "#5c5e66",
    "border": "#d7d9dc",
}


def build_stylesheet(theme: str = "dark") -> str:
    """Gera o QSS completo da aplicação para o tema escolhido."""
    p = DARK if theme != "light" else LIGHT
    return f"""
    QWidget {{
        background-color: {p['bg_mid']};
        color: {p['text']};
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 14px;
    }}
    /* ---------------- Sidebar ---------------- */
    #Sidebar {{
        background-color: {p['bg_darkest']};
        border: none;
    }}
    #Sidebar QPushButton {{
        background: transparent;
        color: {p['text_muted']};
        border: none;
        border-radius: 8px;
        padding: 12px 16px;
        text-align: left;
        font-size: 15px;
        font-weight: 600;
    }}
    #Sidebar QPushButton:hover {{
        background-color: {p['bg_hover']};
        color: {p['text']};
    }}
    #Sidebar QPushButton:checked {{
        background-color: {p['accent']};
        color: white;
    }}
    #AppTitle {{
        color: {p['text']};
        font-size: 18px;
        font-weight: 800;
        background: transparent;
        padding: 16px;
    }}
    /* ---------------- Painéis / Cards ---------------- */
    #Panel, #Card {{
        background-color: {p['bg_dark']};
        border: 1px solid {p['border']};
        border-radius: 10px;
    }}
    #Card:hover {{ border: 1px solid {p['accent']}; }}
    #CardTitle {{ font-size: 15px; font-weight: 700; background: transparent; }}
    #CardMuted {{ color: {p['text_muted']}; background: transparent; }}
    #ScoreBadge {{
        background-color: {p['accent']};
        color: white;
        border-radius: 12px;
        padding: 4px 10px;
        font-weight: 800;
    }}
    #SectionTitle {{
        font-size: 17px;
        font-weight: 800;
        background: transparent;
    }}
    #Muted {{ color: {p['text_muted']}; background: transparent; }}
    /* ---------------- Área de drop ---------------- */
    #DropArea {{
        background-color: {p['bg_dark']};
        border: 2px dashed {p['text_muted']};
        border-radius: 12px;
        color: {p['text_muted']};
    }}
    #DropArea[dragActive="true"] {{
        border: 2px dashed {p['accent']};
        color: {p['accent']};
    }}
    /* ---------------- Controles ---------------- */
    QPushButton {{
        background-color: {p['bg_light']};
        border: none;
        border-radius: 8px;
        padding: 10px 18px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background-color: {p['bg_hover']}; }}
    QPushButton:disabled {{ color: {p['text_muted']}; }}
    QPushButton#Primary {{
        background-color: {p['accent']};
        color: white;
        font-size: 15px;
        font-weight: 700;
    }}
    QPushButton#Primary:hover {{ background-color: {p['accent_hover']}; }}
    QPushButton#Danger {{ background-color: {p['danger']}; color: white; }}
    QPushButton#CategoryButton {{
        background-color: {p['bg_dark']};
        border: 1px solid {p['border']};
        padding: 6px 14px;
    }}
    QPushButton#CategoryButton:hover {{ background-color: {p['bg_hover']}; }}
    QPushButton#CategoryButton:checked {{
        background-color: {p['accent']};
        border: 1px solid {p['accent']};
        color: white;
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background-color: {p['bg_light']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        padding: 8px 10px;
        selection-background-color: {p['accent']};
    }}
    QLineEdit:focus, QComboBox:focus {{ border: 1px solid {p['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{
        background-color: {p['bg_dark']};
        border: 1px solid {p['border']};
        selection-background-color: {p['accent']};
    }}
    QCheckBox::indicator {{
        width: 18px; height: 18px;
        border-radius: 4px;
        border: 1px solid {p['text_muted']};
        background: {p['bg_light']};
    }}
    QCheckBox::indicator:checked {{
        background-color: {p['accent']};
        border: 1px solid {p['accent']};
    }}
    /* ---------------- Progresso ---------------- */
    QProgressBar {{
        background-color: {p['bg_light']};
        border: none;
        border-radius: 8px;
        height: 16px;
        text-align: center;
        color: white;
        font-weight: 700;
    }}
    QProgressBar::chunk {{
        background-color: {p['accent']};
        border-radius: 8px;
    }}
    /* ---------------- Logs ---------------- */
    #LogPanel {{
        background-color: {p['bg_darkest']};
        border: 1px solid {p['border']};
        border-radius: 10px;
        font-family: 'Cascadia Code', 'Consolas', monospace;
        font-size: 12px;
        color: {p['text_muted']};
    }}
    /* ---------------- Tabelas ---------------- */
    QTableWidget {{
        background-color: {p['bg_dark']};
        border: 1px solid {p['border']};
        border-radius: 10px;
        gridline-color: {p['border']};
    }}
    QHeaderView::section {{
        background-color: {p['bg_darkest']};
        border: none;
        padding: 8px;
        font-weight: 700;
    }}
    QTableWidget::item:selected {{ background-color: {p['accent']}; }}
    /* ---------------- Scrollbar ---------------- */
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {p['bg_hover']}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollArea {{ border: none; }}
    """
