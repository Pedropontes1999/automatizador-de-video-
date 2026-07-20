"""Página Editor: edita um vídeo completo (sem cortar em Shorts) — abertura
com narração por IA e/ou transição de estática de TV antes do vídeo original.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.config import constants as C
from src.config.settings import Settings
from src.gui.widgets.drop_area import DropArea
from src.gui.widgets.log_panel import LogPanel
from src.video.downloader import is_youtube_url
from src.workers.audio_download_worker import AudioDownloadWorker


class EditorPage(QWidget):
    """Tela do editor de vídeo completo (narração + estática de abertura)."""

    processRequested = Signal(str)   # caminho do arquivo ou URL
    pauseRequested = Signal()
    resumeRequested = Signal()
    cancelRequested = Signal()

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._source: str | None = None
        self._paused = False
        self._started_at: float | None = None
        self._base_status = "Pronto."
        self._build_ui()
        self._load_values()
        # Cronômetro: mesmo motivo da Home (provar que não travou durante
        # etapas longas como o reencode do vídeo inteiro).
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._refresh_status_label)

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("Editor de Vídeo")
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        subtitle = QLabel(
            "Edite o vídeo inteiro (sem cortar em Shorts): adicione uma narração "
            "por IA no início e/ou uma transição de estática de TV antes do "
            "vídeo original começar."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(10)

        # -- Narração no início -------------------------------------------- #
        form.addRow(self._section("🎙 Narração no início"))
        self.narration_enabled = QCheckBox("Narrar um texto antes do vídeo começar")
        self.narration_voice = QComboBox()
        for voice, label in C.TTS_VOICES.items():
            self.narration_voice.addItem(label, userData=voice)
        self.narration_text = QPlainTextEdit()
        self.narration_text.setPlaceholderText(
            "Texto narrado antes da transição de estática..."
        )
        self.narration_text.setFixedHeight(80)
        form.addRow("", self.narration_enabled)
        form.addRow("Voz:", self.narration_voice)
        form.addRow("Texto:", self.narration_text)

        # -- Música de fundo (toca por baixo da narração) -------------------- #
        form.addRow(self._section("🎵 Música de fundo (toca durante a narração)"))
        self.music_url = QLineEdit()
        self.music_url.setPlaceholderText("Cole o link do YouTube da música...")
        self.music_url.returnPressed.connect(self._download_music_from_youtube)
        self.music_download_btn = QPushButton("⬇ Baixar áudio")
        self.music_download_btn.clicked.connect(self._download_music_from_youtube)
        music_url_row = QWidget()
        music_url_layout = QHBoxLayout(music_url_row)
        music_url_layout.setContentsMargins(0, 0, 0, 0)
        music_url_layout.addWidget(self.music_url, stretch=1)
        music_url_layout.addWidget(self.music_download_btn)
        form.addRow("Link do YouTube:", music_url_row)

        self.music_status = QLabel("")
        self.music_status.setObjectName("Muted")
        form.addRow("", self.music_status)

        self.music_path = QLineEdit()
        self.music_path.setReadOnly(True)
        self.music_path.setPlaceholderText(
            "Nenhuma música (opcional) — ou escolha um arquivo local abaixo"
        )
        form.addRow("Arquivo atual:", self._file_row(self.music_path, self._pick_music))
        self.music_volume = QSpinBox(minimum=0, maximum=100, suffix=" %")
        self.music_volume.setToolTip("Volume da música em relação à narração")
        form.addRow("Volume:", self.music_volume)

        # -- Transição de estática ------------------------------------------ #
        form.addRow(self._section("📺 Transição de estática de TV"))
        self.static_enabled = QCheckBox("Mostrar estática antes do vídeo começar")
        self.static_seconds = QSpinBox(minimum=1, maximum=8, suffix=" s")
        form.addRow("", self.static_enabled)
        form.addRow("Duração:", self.static_seconds)

        root.addLayout(form)

        # -- Entrada: drop area + campo de link ------------------------- #
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

        # -- Ações ------------------------------------------------------- #
        actions = QHBoxLayout()
        self.process_button = QPushButton("✨ Processar vídeo")
        self.process_button.setObjectName("Primary")
        self.process_button.setEnabled(False)
        self.process_button.clicked.connect(self.request_process)
        self.pause_button = QPushButton("⏸ Pausar")
        self.pause_button.setVisible(False)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.cancel_button = QPushButton("✖ Cancelar")
        self.cancel_button.setObjectName("Danger")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancelRequested.emit)
        actions.addWidget(self.process_button, stretch=1)
        actions.addWidget(self.pause_button)
        actions.addWidget(self.cancel_button)
        root.addLayout(actions)

        # -- Progresso ---------------------------------------------------- #
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)
        self.status_label = QLabel("Pronto.")
        self.status_label.setObjectName("Muted")
        root.addWidget(self.status_label)

        self.log_panel = LogPanel()
        root.addWidget(self.log_panel, stretch=1)

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _file_row(self, line_edit: QLineEdit, pick_slot) -> QWidget:
        """Linha com campo somente leitura + botões Escolher/Remover."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        choose = QPushButton("📂 Escolher...")
        choose.clicked.connect(pick_slot)
        clear = QPushButton("✖")
        clear.setToolTip("Remover")
        clear.setFixedWidth(36)
        clear.clicked.connect(lambda: line_edit.setText(""))
        layout.addWidget(line_edit, stretch=1)
        layout.addWidget(choose)
        layout.addWidget(clear)
        return row

    # ------------------------------------------------------------------ #
    def _pick_music(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in C.SUPPORTED_AUDIO_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher música de fundo", "", f"Áudios/Vídeos ({patterns})",
        )
        if path:
            self.music_path.setText(path)

    def _download_music_from_youtube(self) -> None:
        url = self.music_url.text().strip()
        if not is_youtube_url(url):
            QMessageBox.warning(
                self, "Link inválido",
                "Cole um link válido do YouTube (youtube.com ou youtu.be).",
            )
            return
        self.music_download_btn.setEnabled(False)
        self.music_status.setText("Baixando áudio...")
        # Referência guardada na instância: sem isso o QThread seria coletado
        # pelo GC assim que este método retornasse, matando o download.
        self._music_worker = AudioDownloadWorker(url)
        self._music_worker.progressChanged.connect(
            lambda _pct, msg: self.music_status.setText(msg)
        )
        self._music_worker.downloaded.connect(self._on_music_downloaded)
        self._music_worker.failed.connect(self._on_music_download_failed)
        self._music_worker.start()

    def _on_music_downloaded(self, path: str) -> None:
        self.music_path.setText(path)
        self.music_status.setText("✅ Áudio baixado e definido como música de fundo.")
        self.music_download_btn.setEnabled(True)
        self.music_url.clear()

    def _on_music_download_failed(self, message: str) -> None:
        self.music_status.setText("")
        self.music_download_btn.setEnabled(True)
        QMessageBox.warning(self, "Erro ao baixar áudio", message)

    # ------------------------------------------------------------------ #
    def _load_values(self) -> None:
        s = self.settings
        self.narration_enabled.setChecked(s.editor_narration_enabled)
        voice_index = self.narration_voice.findData(s.editor_narration_voice)
        self.narration_voice.setCurrentIndex(max(voice_index, 0))
        self.narration_text.setPlainText(s.editor_narration_text)
        self.music_path.setText(s.editor_music_path)
        self.music_volume.setValue(s.editor_music_volume)
        self.static_enabled.setChecked(s.editor_static_enabled)
        self.static_seconds.setValue(s.editor_static_seconds)

    def _save_values(self) -> None:
        """Persiste as opções da abertura em Settings/config.json."""
        s = self.settings
        s.editor_narration_enabled = self.narration_enabled.isChecked()
        s.editor_narration_voice = self.narration_voice.currentData()
        s.editor_narration_text = self.narration_text.toPlainText().strip()
        s.editor_music_path = self.music_path.text().strip()
        s.editor_music_volume = self.music_volume.value()
        s.editor_static_enabled = self.static_enabled.isChecked()
        s.editor_static_seconds = self.static_seconds.value()
        s.save()

    # ------------------------------------------------------------------ #
    # API pública (usada pela MainWindow)
    # ------------------------------------------------------------------ #
    def set_source(self, source: str) -> None:
        """Define o vídeo/URL de origem e habilita o botão Processar."""
        self._source = source
        display = source if len(source) < 90 else source[:87] + "..."
        self.source_label.setText(f"🎞 {display}")
        self.process_button.setEnabled(True)

    def request_process(self) -> None:
        """Dispara o processamento (valida que há abertura ativa)."""
        if not self._source or not self.process_button.isEnabled():
            return
        if not self.narration_enabled.isChecked() and not self.static_enabled.isChecked():
            self.status_label.setText(
                "⚠ Ative a narração e/ou a transição de estática antes de processar."
            )
            return
        self._save_values()
        self.processRequested.emit(self._source)

    def set_running(self, running: bool) -> None:
        """Alterna o estado visual entre ocioso e processando."""
        self.process_button.setEnabled(not running and self._source is not None)
        self.pause_button.setVisible(running)
        self.pause_button.setEnabled(running)
        self.cancel_button.setVisible(running)
        self.cancel_button.setEnabled(running)
        if running:
            self._started_at = time.monotonic()
            self._elapsed_timer.start()
        else:
            self._elapsed_timer.stop()
            self._started_at = None
            self._paused = False
            self.pause_button.setText("⏸ Pausar")

    def set_cancelling(self) -> None:
        """Feedback imediato ao pedir cancelamento (não é instantâneo: a
        etapa de reencode em andamento precisa terminar antes de abortar)."""
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self._base_status = "Cancelando... aguardando a etapa atual terminar."
        self._refresh_status_label()

    def update_progress(self, percent: int, message: str) -> None:
        """Atualiza a barra de progresso e o status."""
        self.progress.setValue(percent)
        self._base_status = message
        self._refresh_status_label()

    def _refresh_status_label(self) -> None:
        """Reescreve o status incluindo o tempo decorrido (prova de vida)."""
        if self._started_at is None:
            self.status_label.setText(self._base_status)
            return
        elapsed = int(time.monotonic() - self._started_at)
        clock = f"{elapsed // 60:02d}:{elapsed % 60:02d}"
        self.status_label.setText(f"{self._base_status}  ⏱ {clock}")

    # ------------------------------------------------------------------ #
    def _use_url(self) -> None:
        """Valida e usa o link do YouTube digitado."""
        url = self.url_input.text().strip()
        if is_youtube_url(url):
            self.set_source(url)
        else:
            self.status_label.setText("⚠ Link inválido: cole um link do YouTube.")

    def _toggle_pause(self) -> None:
        """Alterna entre pausar e retomar."""
        self._paused = not self._paused
        if self._paused:
            self.pause_button.setText("▶ Retomar")
            self.pauseRequested.emit()
        else:
            self.pause_button.setText("⏸ Pausar")
            self.resumeRequested.emit()
