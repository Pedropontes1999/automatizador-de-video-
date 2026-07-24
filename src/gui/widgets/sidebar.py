"""Sidebar de navegação (estilo Discord)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QLabel, QPushButton, QVBoxLayout, QWidget


class Sidebar(QWidget):
    """Barra lateral com os botões de navegação entre páginas."""

    pageSelected = Signal(int)

    #: (ícone emoji, rótulo) na ordem das páginas do QStackedWidget.
    ITEMS: tuple[tuple[str, str], ...] = (
        ("🪄", "Editar Shorts"),
        ("⬇️", "Download"),
        ("🗣️", "Redublagem"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Sidebar")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 16)
        layout.setSpacing(4)

        title = QLabel("⚡ AUTO SHORTS AI")
        title.setObjectName("AppTitle")
        layout.addWidget(title)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, (icon, label) in enumerate(self.ITEMS):
            button = QPushButton(f"{icon}  {label}")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _=False, i=index: self.pageSelected.emit(i))
            self._group.addButton(button, index)
            layout.addWidget(button)

        layout.addStretch()
        version = QLabel("v1.0.0 • 100% local")
        version.setObjectName("Muted")
        layout.addWidget(version)

    def set_current_index(self, index: int) -> None:
        """Marca o botão correspondente como selecionado (navegação vinda de
        fora da sidebar, ex.: botão "Editar Shorts" da Download)."""
        button = self._group.button(index)
        if button is not None:
            button.setChecked(True)
