"""Página Download: baixa um vídeo do YouTube (via link) para downloads/,
sem nenhum processamento — só pra ter o arquivo local. De lá, dá pra mandar
direto pra Editar Shorts com um clique.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.utils.logger import get_logger
from src.video.downloader import is_youtube_url
from src.workers.download_worker import DownloadWorker

logger = get_logger("download_page")


class DownloadPage(QWidget):
    """Baixa vídeos do YouTube pra usar em qualquer outra aba do app."""

    openInEditor = Signal(str)  # caminho do vídeo baixado

    def __init__(self) -> None:
        super().__init__()
        self._worker: DownloadWorker | None = None
        self._last_output: str | None = None
        self._build_ui()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        title = QLabel("Download")
        title.setObjectName("SectionTitle")
        outer.addWidget(title)
        subtitle = QLabel(
            "Cole o link de um vídeo do YouTube (apenas vídeos autorizados por "
            "você) para baixar em MP4 na pasta downloads/. Depois é só mandar "
            "direto pra Editar Shorts, ou usar em qualquer outra aba."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        url_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Cole o link do YouTube aqui...")
        self.url_input.returnPressed.connect(self._start_download)
        self.download_button = QPushButton("⬇ Baixar")
        self.download_button.setObjectName("Primary")
        self.download_button.clicked.connect(self._start_download)
        url_row.addWidget(self.url_input, stretch=1)
        url_row.addWidget(self.download_button)
        outer.addLayout(url_row)

        outer.addStretch()

        actions = QHBoxLayout()
        self.editor_button = QPushButton("🎬 Editar Shorts")
        self.editor_button.setVisible(False)
        self.editor_button.clicked.connect(self._send_to_editor)
        self.open_folder_button = QPushButton("📂 Abrir pasta")
        self.open_folder_button.setVisible(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        actions.addWidget(self.editor_button, stretch=1)
        actions.addWidget(self.open_folder_button)
        outer.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        outer.addWidget(self.progress)
        self.status_label = QLabel("Pronto.")
        self.status_label.setObjectName("Muted")
        outer.addWidget(self.status_label)

    # ------------------------------------------------------------------ #
    def is_running(self) -> bool:
        """Indica se há um download em andamento (usado ao fechar a janela)."""
        return self._worker is not None and self._worker.isRunning()

    def wait_running_worker(self, timeout_ms: int) -> bool:
        """Aguarda o worker atual encerrar; True se terminou dentro do prazo."""
        if self._worker is None:
            return True
        return self._worker.wait(timeout_ms)

    def terminate_running_worker(self) -> None:
        """Força o encerramento do worker (último recurso, ao fechar o app)."""
        if self._worker is not None:
            self._worker.terminate()
            self._worker.wait(3000)

    # ------------------------------------------------------------------ #
    def _start_download(self) -> None:
        if self.is_running():
            return
        url = self.url_input.text().strip()
        if not is_youtube_url(url):
            QMessageBox.warning(
                self, "Link inválido", "Cole um link válido do YouTube.",
            )
            return

        self._worker = DownloadWorker(url)
        self._worker.progressChanged.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

        self.download_button.setEnabled(False)
        self.editor_button.setVisible(False)
        self.open_folder_button.setVisible(False)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.status_label.setText("Iniciando...")

    def _on_progress(self, percent: int, message: str) -> None:
        self.progress.setValue(percent)
        self.status_label.setText(message)

    def _on_succeeded(self, output_path: str) -> None:
        self._last_output = output_path
        self.download_button.setEnabled(True)
        self.progress.setVisible(False)
        self.status_label.setText(f"Concluído: {output_path}")
        self.editor_button.setVisible(True)
        self.open_folder_button.setVisible(True)

    def _on_failed(self, message: str) -> None:
        self.download_button.setEnabled(True)
        self.progress.setVisible(False)
        self.status_label.setText("Erro ao baixar.")
        QMessageBox.warning(self, "Erro ao baixar vídeo", message)

    def _send_to_editor(self) -> None:
        if self._last_output:
            self.openInEditor.emit(self._last_output)

    def _open_output_folder(self) -> None:
        if not self._last_output:
            return
        folder = str(Path(self._last_output).parent)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
