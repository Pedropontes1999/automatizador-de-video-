"""Card visual de um corte gerado (título, nota, categoria, ações)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.models.domain import CutCandidate

_STATUS_ICONS = {
    "pending": "⏳", "processing": "⚙️", "done": "✅", "error": "❌",
}


def _fmt_clock(seconds: float) -> str:
    """Formata segundos como mm:ss."""
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


class CutCard(QWidget):
    """Card com as informações de um corte e botão para abrir o arquivo."""

    def __init__(self, cut: CutCandidate) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._cut = cut

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(6)

        # Linha 1: status + título + nota
        top = QHBoxLayout()
        icon = _STATUS_ICONS.get(cut.status, "⏳")
        title = QLabel(f"{icon} {cut.title}")
        title.setObjectName("CardTitle")
        title.setWordWrap(True)
        top.addWidget(title, stretch=1)
        # Cortes sequenciais (tempo fixo) não passam pela IA: sem nota viral.
        if cut.category != "sequencial":
            score = QLabel(f"{cut.score}")
            score.setObjectName("ScoreBadge")
            score.setToolTip("Nota viral (0-100)")
            top.addWidget(score)
        root.addLayout(top)

        # Linha 2: metadados
        meta = QLabel(
            f"{_fmt_clock(cut.start)} → {_fmt_clock(cut.end)}  •  "
            f"{cut.duration:.0f}s  •  {cut.category}  •  "
            f"{' '.join(cut.hashtags[:4])}"
        )
        meta.setObjectName("CardMuted")
        meta.setWordWrap(True)
        root.addWidget(meta)

        # Linha 3: motivo da IA
        if cut.reason:
            reason = QLabel(f"💡 {cut.reason}")
            reason.setObjectName("CardMuted")
            reason.setWordWrap(True)
            root.addWidget(reason)

        # Linha 4: ações
        if cut.output_path:
            actions = QHBoxLayout()
            open_btn = QPushButton("▶ Abrir")
            open_btn.clicked.connect(self._open_file)
            folder_btn = QPushButton("📁 Pasta")
            folder_btn.clicked.connect(self._open_folder)
            actions.addWidget(open_btn)
            actions.addWidget(folder_btn)
            actions.addStretch()
            root.addLayout(actions)

    # ------------------------------------------------------------------ #
    def _open_file(self) -> None:
        """Abre o MP4 no player padrão do sistema."""
        if self._cut.output_path and Path(self._cut.output_path).exists():
            if sys.platform == "win32":
                import os
                os.startfile(self._cut.output_path)  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", self._cut.output_path])

    def _open_folder(self) -> None:
        """Abre a pasta do corte no Explorer."""
        if self._cut.output_path:
            folder = str(Path(self._cut.output_path).parent)
            if sys.platform == "win32":
                subprocess.Popen(["explorer", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
