"""Linha da lista de cortes pendentes (aba Cortar Vídeo): intervalo + remover."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from src.video.trim_editor import CutRange


def _fmt_clock(seconds: float) -> str:
    """Formata segundos como mm:ss.s."""
    minutes, secs = divmod(max(seconds, 0.0), 60)
    return f"{int(minutes):02d}:{secs:04.1f}"


class TrimRangeRow(QWidget):
    """Card com o intervalo marcado e botão para remover da lista."""

    removeRequested = Signal(object)  # emite a própria CutRange

    def __init__(self, cut: CutRange) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.cut = cut

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        label = QLabel(
            f"✂ {_fmt_clock(cut.start)} → {_fmt_clock(cut.end)}  "
            f"({cut.end - cut.start:.2f}s removidos)"
        )
        layout.addWidget(label, stretch=1)
        remove_btn = QPushButton("✖")
        remove_btn.setToolTip("Remover da lista")
        remove_btn.setFixedWidth(36)
        remove_btn.clicked.connect(lambda: self.removeRequested.emit(self.cut))
        layout.addWidget(remove_btn)
