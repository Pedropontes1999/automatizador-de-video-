"""Página Transcrição: transcreve um vídeo (local ou link do YouTube) com
Whisper e abre a modal de exportação (visualizar, editar, copiar, exportar
TXT/DOCX/MD e gerar prompts prontos pra IA).

Fica desacoplada dos pipelines de Cortes e Redublagem — que já transcrevem
internamente, mas rodam do início ao fim numa thread de fundo sem parar pra
interação do usuário. Aqui a transcrição é o produto final da tela.
"""
from __future__ import annotations

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

from src.config.settings import Settings
from src.gui.dialogs.transcript_dialog import TranscriptDialog
from src.gui.widgets.drop_area import DropArea
from src.models.domain import Transcription
from src.video.downloader import is_youtube_url
from src.workers.transcribe_worker import TranscribeWorker


class TranscriptPage(QWidget):
    """Tela de Transcrição por IA (com exportação editável)."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._source: str | None = None
        self._worker: TranscribeWorker | None = None
        self._build_ui()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("Transcrição")
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        subtitle = QLabel(
            "Envie um vídeo e a IA (Whisper) reconhece toda a narração. Ao "
            "terminar, uma janela abre com o texto pronto pra revisar, "
            "copiar ou exportar em TXT, DOCX, Markdown — ou já num formato "
            "pronto pra colar num ChatGPT/Claude."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self.drop_area = DropArea()
        self.drop_area.fileSelected.connect(self.set_source)
        root.addWidget(self.drop_area)

        url_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "Ou cole um link do YouTube (apenas vídeos autorizados por você)..."
        )
        self.url_input.returnPressed.connect(self._use_url)
        url_button = QPushButton("Usar link")
        url_button.clicked.connect(self._use_url)
        url_row.addWidget(self.url_input, stretch=1)
        url_row.addWidget(url_button)
        root.addLayout(url_row)

        self.source_label = QLabel("Nenhum vídeo selecionado.")
        self.source_label.setObjectName("Muted")
        root.addWidget(self.source_label)

        actions = QHBoxLayout()
        self.process_button = QPushButton("📝 Transcrever")
        self.process_button.setObjectName("Primary")
        self.process_button.setEnabled(False)
        self.process_button.clicked.connect(self._process)
        actions.addWidget(self.process_button, stretch=1)
        root.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminado: Whisper não reporta %
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.status_label = QLabel("Pronto.")
        self.status_label.setObjectName("Muted")
        root.addWidget(self.status_label)

        root.addStretch()

    # ------------------------------------------------------------------ #
    # Fonte
    # ------------------------------------------------------------------ #
    def set_source(self, source: str) -> None:
        self._source = source
        display = source if len(source) < 90 else source[:87] + "..."
        self.source_label.setText(f"🎞 {display}")
        self.process_button.setEnabled(True)

    def _use_url(self) -> None:
        url = self.url_input.text().strip()
        if is_youtube_url(url):
            self.set_source(url)
        else:
            self.status_label.setText("⚠ Link inválido: cole um link do YouTube.")

    # ------------------------------------------------------------------ #
    # Processamento
    # ------------------------------------------------------------------ #
    def is_running(self) -> bool:
        """Indica se há uma transcrição em andamento (usado ao fechar a janela)."""
        return self._worker is not None and self._worker.isRunning()

    def wait_running_worker(self, timeout_ms: int) -> bool:
        if self._worker is None:
            return True
        return self._worker.wait(timeout_ms)

    def terminate_running_worker(self) -> None:
        if self._worker is not None:
            self._worker.terminate()
            self._worker.wait(3000)

    def _process(self) -> None:
        if self._source is None:
            return
        self._worker = TranscribeWorker(self.settings, self._source)
        self._worker.progressChanged.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

        self.process_button.setEnabled(False)
        self.progress.setVisible(True)
        self.status_label.setText("Iniciando...")

    def _on_progress(self, message: str) -> None:
        self.status_label.setText(message)

    def _on_succeeded(self, transcription: Transcription, video_title: str) -> None:
        self.progress.setVisible(False)
        self.status_label.setText("Transcrição concluída.")
        self.process_button.setEnabled(self._source is not None)
        dialog = TranscriptDialog(transcription, video_title, self.settings, parent=self)
        dialog.exec()

    def _on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.status_label.setText("Erro na transcrição.")
        self.process_button.setEnabled(self._source is not None)
        QMessageBox.warning(self, "Erro na transcrição", message)
