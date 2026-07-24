"""Página Redublagem: troca a voz do narrador de um vídeo já pronto por uma
narração de IA sincronizada por trecho. O áudio original inteiro (voz +
música/efeitos) é descartado e substituído por uma música de fundo escolhida
pelo usuário, tocando em loop do início ao fim do vídeo.

Fluxo em duas etapas — o objetivo não é só trocar o timbre da voz, é permitir
reescrever a narração com outras palavras antes de gerar a voz nova:

1. "Transcrever": a IA separa a voz, transcreve e mostra o texto original,
   um trecho por linha.
2. O usuário reescreve o texto (linha por linha; pode copiar/colar num
   ChatGPT/Claude e pedir pra reescrever "sem copiar as frases originais").
3. "Gerar vídeo": a IA sintetiza a narração nova em cima do texto revisado,
   sincronizada por trecho com o tempo original, e substitui a voz no vídeo.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
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

    transcribeRequested = Signal(str)   # caminho do arquivo ou URL (etapa 1)
    translateRequested = Signal(object)  # list[str] a traduzir (etapa 1.5, opcional)
    generateRequested = Signal(object)  # list[str], uma linha por trecho (etapa 2)
    pauseRequested = Signal()
    resumeRequested = Signal()
    cancelRequested = Signal()

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._source: str | None = None
        self._segment_count = 0
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

        # -- Música de fundo ----------------------------------------------- #
        form.addRow(self._section("🎵 Música de fundo"))
        music_hint = QLabel(
            "O áudio original do vídeo (voz + música/efeitos) é sempre "
            "descartado. Escolha uma música pra tocar em loop do início ao "
            "fim, por baixo da nova narração — sem escolher nenhuma, o "
            "vídeo sai só com a narração."
        )
        music_hint.setObjectName("Muted")
        music_hint.setWordWrap(True)
        form.addRow(music_hint)
        self.music_path = QLineEdit()
        self.music_path.setReadOnly(True)
        self.music_path.setPlaceholderText("Nenhuma música escolhida (opcional)")
        form.addRow("Arquivo:", self._file_row(self.music_path, self._pick_music))
        self.music_volume = QSpinBox(minimum=0, maximum=150, suffix=" %")
        self.music_volume.setToolTip("Volume da música em relação à nova narração")
        form.addRow("Volume:", self.music_volume)

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

        # -- Revisão do texto (aparece depois da etapa 1) ----------------- #
        self.review_container = QWidget()
        review_layout = QVBoxLayout(self.review_container)
        review_layout.setContentsMargins(0, 0, 0, 0)
        review_layout.setSpacing(8)
        review_layout.addWidget(self._section("✏️ Revise a narração antes de gerar a nova voz"))
        review_subtitle = QLabel(
            "Reescreva o texto abaixo com outras palavras (pode copiar tudo, "
            "colar num ChatGPT/Claude e pedir pra reescrever sem copiar as "
            "frases originais, e colar o resultado de volta aqui). Cada "
            "linha é um trecho sincronizado com o tempo original do vídeo "
            "— não apague nem quebre linhas, só reescreva o conteúdo de "
            "cada uma."
        )
        review_subtitle.setObjectName("Muted")
        review_subtitle.setWordWrap(True)
        review_layout.addWidget(review_subtitle)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setMinimumHeight(220)
        self.text_edit.setPlaceholderText("O texto transcrito aparece aqui após a etapa 1...")
        self.text_edit.textChanged.connect(self._update_line_count)
        review_layout.addWidget(self.text_edit)
        text_actions = QHBoxLayout()
        self.copy_button = QPushButton("📋 Copiar texto")
        self.copy_button.clicked.connect(self._copy_text)
        self.translate_button = QPushButton("🌐 Traduzir p/ PT-BR (IA)")
        self.translate_button.setToolTip(
            "Traduz o texto acima para português do Brasil usando o Ollama "
            "local, mantendo a quantidade de linhas. Use quando o vídeo "
            "original está em outro idioma — a voz de narração é só em "
            "PT-BR, então o texto precisa estar em português antes de gerar."
        )
        self.translate_button.clicked.connect(self.request_translate)
        self.line_count_label = QLabel("")
        self.line_count_label.setObjectName("Muted")
        text_actions.addWidget(self.copy_button)
        text_actions.addWidget(self.translate_button)
        text_actions.addWidget(self.line_count_label, stretch=1)
        review_layout.addLayout(text_actions)
        self.review_container.setVisible(False)
        content_layout.addWidget(self.review_container)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)

        # -- Ações ------------------------------------------------------- #
        actions = QHBoxLayout()
        self.transcribe_button = QPushButton("📝 1. Transcrever narração")
        self.transcribe_button.setObjectName("Primary")
        self.transcribe_button.setEnabled(False)
        self.transcribe_button.clicked.connect(self.request_transcribe)
        self.generate_button = QPushButton("🎙 2. Gerar vídeo com nova voz")
        self.generate_button.setObjectName("Primary")
        self.generate_button.setVisible(False)
        self.generate_button.clicked.connect(self.request_generate)
        self.pause_button = QPushButton("⏸ Pausar")
        self.pause_button.setVisible(False)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.cancel_button = QPushButton("✖ Cancelar")
        self.cancel_button.setObjectName("Danger")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancelRequested.emit)
        actions.addWidget(self.transcribe_button, stretch=1)
        actions.addWidget(self.generate_button, stretch=1)
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

    def _pick_music(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in C.SUPPORTED_AUDIO_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher música de fundo", "", f"Áudios/Vídeos ({patterns})",
        )
        if path:
            self.music_path.setText(path)

    # ------------------------------------------------------------------ #
    def _load_values(self) -> None:
        s = self.settings
        voice_index = self.voice.findData(s.redub_voice)
        self.voice.setCurrentIndex(max(voice_index, 0))
        self.music_path.setText(s.redub_music_path)
        self.music_volume.setValue(s.redub_music_volume)

    def save(self) -> None:
        """Persiste as opções da Redublagem (usado pelo atalho Ctrl+S)."""
        self._save_values()

    def _save_values(self) -> None:
        """Persiste as opções da Redublagem em Settings/config.json."""
        s = self.settings
        s.redub_voice = self.voice.currentData()
        s.redub_music_path = self.music_path.text().strip()
        s.redub_music_volume = self.music_volume.value()
        s.save()

    # ------------------------------------------------------------------ #
    # API pública (usada pela MainWindow)
    # ------------------------------------------------------------------ #
    def set_source(self, source: str) -> None:
        """Define o vídeo/URL de origem e habilita o botão Transcrever."""
        self._source = source
        display = source if len(source) < 90 else source[:87] + "..."
        self.source_label.setText(f"🎞 {display}")
        self.transcribe_button.setEnabled(True)
        self._reset_review()

    def _reset_review(self) -> None:
        """Esconde a revisão de texto: um vídeo novo invalida a transcrição
        (e a preparação) da etapa 1 anterior."""
        self._segment_count = 0
        self.text_edit.clear()
        self.review_container.setVisible(False)
        self.generate_button.setVisible(False)

    def request_transcribe(self) -> None:
        """Dispara a etapa 1: transcrição + separação de voz/música."""
        if not self._source or not self.transcribe_button.isEnabled():
            return
        self._save_values()
        self._reset_review()
        self.transcribeRequested.emit(self._source)

    def show_transcription(self, segment_texts: list[str]) -> None:
        """Preenche a caixa de revisão com o texto original, um trecho por
        linha (chamado pela MainWindow quando a etapa 1 termina)."""
        self._segment_count = len(segment_texts)
        self.text_edit.setPlainText("\n".join(segment_texts))
        self.review_container.setVisible(True)
        self.generate_button.setVisible(True)
        self.generate_button.setEnabled(True)
        self.translate_button.setEnabled(True)
        self._update_line_count()

    def request_translate(self) -> None:
        """Dispara a tradução (via IA local/Ollama) do texto revisado para
        PT-BR — usada quando o vídeo original está em outro idioma."""
        if not self.translate_button.isEnabled():
            return
        lines = self.text_edit.toPlainText().split("\n")
        if len(lines) != self._segment_count:
            QMessageBox.warning(
                self, "Número de linhas não bate",
                f"O texto tem {len(lines)} linha(s), mas o vídeo original "
                f"tem {self._segment_count} trecho(s) falados. Não apague "
                "nem quebre linhas antes de traduzir.",
            )
            return
        self.translateRequested.emit(lines)

    def apply_translation(self, texts: list[str]) -> None:
        """Substitui o texto de revisão pela tradução (chamado pela
        MainWindow quando a tradução termina)."""
        self.text_edit.setPlainText("\n".join(texts))
        self._update_line_count()

    def set_translating(self, running: bool) -> None:
        """Alterna o estado visual durante a tradução — mais rápida que
        transcrever/gerar, então não usa cronômetro nem pausa/cancela."""
        self.transcribe_button.setEnabled(not running and self._source is not None)
        self.generate_button.setEnabled(not running and self._segment_count > 0)
        self.translate_button.setEnabled(not running and self._segment_count > 0)
        self.text_edit.setReadOnly(running)

    def request_generate(self) -> None:
        """Dispara a etapa 2: gera a nova narração a partir do texto revisado."""
        if not self.generate_button.isEnabled():
            return
        lines = self.text_edit.toPlainText().split("\n")
        if len(lines) != self._segment_count:
            QMessageBox.warning(
                self, "Número de linhas não bate",
                f"O texto tem {len(lines)} linha(s), mas o vídeo original "
                f"tem {self._segment_count} trecho(s) falados. Não apague "
                "nem quebre linhas — edite só o conteúdo de cada uma.",
            )
            return
        self._save_values()
        self.generateRequested.emit(lines)

    def _copy_text(self) -> None:
        """Copia o texto revisado pra área de transferência (pra colar num
        ChatGPT/Claude e pedir pra reescrever)."""
        QGuiApplication.clipboard().setText(self.text_edit.toPlainText())

    def _update_line_count(self) -> None:
        """Feedback em tempo real: avisa se o número de linhas não bate mais
        com os trechos originais (usuário apagou/quebrou alguma linha)."""
        if self._segment_count == 0:
            self.line_count_label.setText("")
            return
        count = len(self.text_edit.toPlainText().split("\n"))
        if count == self._segment_count:
            self.line_count_label.setText(f"✔ {count} linha(s) — bate com os trechos originais.")
        else:
            self.line_count_label.setText(
                f"⚠ {count} linha(s), mas o original tem {self._segment_count} — "
                "não apague/quebre linhas."
            )

    def set_running(self, running: bool) -> None:
        """Alterna o estado visual entre ocioso e processando."""
        self.transcribe_button.setEnabled(not running and self._source is not None)
        self.generate_button.setEnabled(not running and self._segment_count > 0)
        self.translate_button.setEnabled(not running and self._segment_count > 0)
        self.text_edit.setReadOnly(running)
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
