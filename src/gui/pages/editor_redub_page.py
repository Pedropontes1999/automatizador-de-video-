"""Página combinada Editor/Redublagem: agrupa a abertura com narração (Editor)
e a troca de narração por IA (Redublagem) numa mesma aba da sidebar, cada uma
numa sub-aba própria. As duas continuam sendo pipelines independentes —
isso só muda onde elas aparecem na navegação.
"""
from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget


class EditorRedubPage(QWidget):
    """Agrupa as páginas Editor e Redublagem em sub-abas."""

    def __init__(self, editor_page: QWidget, redub_page: QWidget) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.addTab(editor_page, "🎬 Abertura")
        self.tabs.addTab(redub_page, "🗣️ Redublagem")
        layout.addWidget(self.tabs)
