"""Página Redublagem: troca a voz do narrador de um vídeo já pronto por uma
narração de IA sincronizada por trecho, mantendo (opcionalmente) a
música/efeitos de fundo originais via separação por IA (Demucs).
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.config import constants as C
from src.config.settings import Settings
from src.gui.widgets.drop_area import DropArea
from src.gui.widgets.log_panel import LogPanel
from src.video.downloader import is_youtube_url


class RedubPage(QWidget):
    """Tela da Redublagem por IA."""

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
        # Cronômetro: mesmo motivo das outras páginas de processamento
        # (transcrição + separação de voz + narração levam vários minutos).
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._refresh_status_label)

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        title = QLabel("Redublagem por IA")
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        subtitle = QLabel(
            "Envie um vídeo já narrado (resumo de anime/mangá, por exemplo) e "
            "troque a voz do narrador por uma narração de IA, sincronizada "
            "trecho a trecho com o tempo da fala original. A música e os "
            "efeitos sonoros do vídeo podem ser mantidos."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # Formulário + entrada de vídeo ficam num painel rolável: assim a
        # janela pode ser reduzida na vertical sem cortar os campos.
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(10)

        # -- Voz da nova narração --------------------------------------- #
        form.addRow(self._section("🎙 Nova narração"))
        self.voice = QComboBox()
        for voice, label in C.TTS_VOICES.items():
            self.voice.addItem(label, userData=voice)
        form.addRow("Voz:", self.voice)

        # -- Clonagem de voz (opcional) ------------------------------------ #
        clone_row = QHBoxLayout()
        self.voice_reference_input = QLineEdit()
        self.voice_reference_input.setPlaceholderText(
            "Nenhum (usa a voz pronta selecionada acima)"
        )
        self.voice_reference_input.setReadOnly(True)
        clone_button = QPushButton("Selecionar áudio...")
        clone_button.clicked.connect(self._pick_voice_reference)
        clone_clear = QPushButton("✖")
        clone_clear.setToolTip("Remover áudio de referência")
        clone_clear.setFixedWidth(28)
        clone_clear.clicked.connect(self._clear_voice_reference)
        clone_row.addWidget(self.voice_reference_input, stretch=1)
        clone_row.addWidget(clone_button)
        clone_row.addWidget(clone_clear)
        clone_label = QLabel("Clonar voz de um áudio:")
        clone_label.setToolTip(
            "Opcional: em vez de usar uma das vozes prontas acima, clona a "
            "voz de um áudio de referência (10-30s de fala limpa, uma só "
            "pessoa, sem música/ruído de fundo) — costuma soar bem mais "
            "natural que os speakers prontos do XTTS."
        )
        form.addRow(clone_label, clone_row)

        # -- Música/efeitos de fundo -------------------------------------- #
        form.addRow(self._section("🎵 Música e efeitos de fundo"))
        self.keep_background = QCheckBox(
            "Manter a música/efeitos do vídeo original (separação por IA)"
        )
        self.keep_background.setToolTip(
            "Usa IA (Demucs) para separar a voz do narrador do resto do "
            "áudio. Pode demorar bastante em vídeos longos sem GPU."
        )
        self.background_volume = QSpinBox(minimum=0, maximum=150, suffix=" %")
        self.background_volume.setToolTip(
            "Volume da música/efeitos originais em relação à nova narração"
        )
        form.addRow("", self.keep_background)
        form.addRow("Volume:", self.background_volume)

        content_layout.addLayout(form)

        # -- Entrada: drop area + campo de link ------------------------- #
        self.drop_area = DropArea()
        self.drop_area.fileSelected.connect(self.set_source)
        content_layout.addWidget(self.drop_area)

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
        content_layout.addLayout(url_row)

        self.source_label = QLabel("Nenhum vídeo selecionado.")
        self.source_label.setObjectName("Muted")
        content_layout.addWidget(self.source_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

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

    # ------------------------------------------------------------------ #
    def _load_values(self) -> None:
        s = self.settings
        voice_index = self.voice.findData(s.redub_voice)
        self.voice.setCurrentIndex(max(voice_index, 0))
        self.voice_reference_input.setText(s.redub_voice_reference)
        self.keep_background.setChecked(s.redub_keep_background)
        self.background_volume.setValue(s.redub_background_volume)

    def save(self) -> None:
        """Persiste as opções da Redublagem (usado pelo atalho Ctrl+S)."""
        self._save_values()

    def _save_values(self) -> None:
        """Persiste as opções da Redublagem em Settings/config.json."""
        s = self.settings
        s.redub_voice = self.voice.currentData()
        s.redub_voice_reference = self.voice_reference_input.text().strip()
        s.redub_keep_background = self.keep_background.isChecked()
        s.redub_background_volume = self.background_volume.value()
        s.save()

    def _pick_voice_reference(self) -> None:
        """Escolhe um áudio de referência pra clonagem de voz (XTTS)."""
        exts = " ".join(f"*{ext}" for ext in C.SUPPORTED_AUDIO_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar áudio de referência", "", f"Áudio ({exts})",
        )
        if path:
            self.voice_reference_input.setText(str(Path(path)))

    def _clear_voice_reference(self) -> None:
        self.voice_reference_input.clear()

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
        """Dispara o processamento."""
        if not self._source or not self.process_button.isEnabled():
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
        etapa atual — transcrição, separação ou render — precisa terminar
        antes de abortar)."""
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
