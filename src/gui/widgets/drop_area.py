"""Área de entrada de vídeo: clique para selecionar, arrastar arquivo
ou colar link do YouTube.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog, QLabel, QVBoxLayout, QWidget

from src.config.constants import SUPPORTED_VIDEO_EXTENSIONS


class DropArea(QWidget):
    """Widget drag & drop que emite o caminho do vídeo selecionado."""

    fileSelected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DropArea")
        self.setAcceptDrops(True)
        self.setMinimumHeight(150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = QLabel("📂")
        icon.setStyleSheet("font-size: 40px; background: transparent;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel("Arraste um vídeo aqui\nou clique para selecionar")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setStyleSheet("background: transparent;")
        layout.addWidget(icon)
        layout.addWidget(text)

    # -- clique ---------------------------------------------------------- #
    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """Abre o seletor de arquivos ao clicar na área."""
        patterns = " ".join(f"*{ext}" for ext in SUPPORTED_VIDEO_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar vídeo", "", f"Vídeos ({patterns})",
        )
        if path:
            self.fileSelected.emit(path)
        super().mousePressEvent(event)

    # -- drag & drop ------------------------------------------------------ #
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        """Aceita apenas arquivos de vídeo suportados."""
        if self._extract_video(event) is not None:
            self.setProperty("dragActive", True)
            self._refresh_style()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.setProperty("dragActive", False)
        self._refresh_style()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        """Emite o caminho do vídeo solto na área."""
        self.setProperty("dragActive", False)
        self._refresh_style()
        path = self._extract_video(event)
        if path is not None:
            self.fileSelected.emit(str(path))

    @staticmethod
    def _extract_video(event) -> Path | None:
        """Retorna o primeiro arquivo de vídeo válido do evento (ou None)."""
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
                return path
        return None

    def _refresh_style(self) -> None:
        """Força a reavaliação do QSS após mudar a propriedade dragActive."""
        self.style().unpolish(self)
        self.style().polish(self)
