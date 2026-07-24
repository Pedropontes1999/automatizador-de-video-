"""Página Estilo: identidade visual dos Shorts e narração por IA.

Aqui o usuário define o "preset" aplicado automaticamente a todo corte
exportado: marca d'água, texto de gancho, "Parte X", barra de progresso,
música de fundo e narração (voz ElevenLabs, nuvem).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
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
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.config import constants as C
from src.config.settings import Settings
from src.gui.widgets.drop_area import DropArea
from src.utils.logger import get_logger
from src.utils.paths import sanitize_filename
from src.video.downloader import is_youtube_url
from src.video.simple_editor import EditOptions
from src.workers.audio_download_worker import AudioDownloadWorker
from src.workers.simple_editor_worker import SimpleEditorWorker

logger = get_logger("style_page")


class StylePage(QWidget):
    """Formulário do preset de estilo, salvo em config.json."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        # Debounce para campos de texto: evita gravar em disco a cada tecla.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save)
        self._test_source: str | None = None
        self._test_worker: SimpleEditorWorker | None = None
        self._test_last_output: str | None = None
        self._build_ui()
        self._load_values()
        self._connect_autosave()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)

        title = QLabel("Estilo dos Shorts")
        title.setObjectName("SectionTitle")
        outer.addWidget(title)
        subtitle = QLabel(
            "Tudo aqui é aplicado automaticamente em todos os cortes exportados. "
            "Deixe em branco o que ainda não quiser usar."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(10)

        # -- Canal --------------------------------------------------------- #
        form.addRow(self._section("📺 Canal (selo com foto, nome e @)"))
        self.channel_name = QLineEdit()
        self.channel_name.setPlaceholderText("Ex.: Tio Shimeji")
        self.channel_handle = QLineEdit()
        self.channel_handle.setPlaceholderText("Ex.: @_shimeji_")
        self.channel_avatar = QLineEdit()
        self.channel_avatar.setReadOnly(True)
        self.channel_avatar.setPlaceholderText("Foto do canal (opcional)")
        self.badge_position = QComboBox()
        for slug, label in C.BADGE_POSITIONS.items():
            self.badge_position.addItem(label, userData=slug)
        form.addRow("Nome do canal:", self.channel_name)
        form.addRow("Arroba (@):", self.channel_handle)
        form.addRow("Foto:", self._file_row(self.channel_avatar, self._pick_avatar))
        form.addRow("Posição do selo:", self.badge_position)

        # -- Enquadramento do anime ----------------------------------------- #
        form.addRow(self._section("🎞 Enquadramento 9:16 (modo anime)"))
        self.anime_framing = QComboBox()
        for slug, label in C.ANIME_FRAMING.items():
            self.anime_framing.addItem(label, userData=slug)
        form.addRow("Formato:", self.anime_framing)

        # -- Marca d'água ------------------------------------------------- #
        form.addRow(self._section("🖼 Marca d'água"))
        self.watermark_path = QLineEdit()
        self.watermark_path.setReadOnly(True)
        self.watermark_path.setPlaceholderText("Nenhuma imagem escolhida (opcional)")
        form.addRow("Imagem:", self._file_row(
            self.watermark_path, self._pick_watermark,
        ))
        self.watermark_position = QComboBox()
        for slug, label in C.WATERMARK_POSITIONS.items():
            self.watermark_position.addItem(label, userData=slug)
        self.watermark_size = QSpinBox(minimum=5, maximum=40, suffix=" %")
        self.watermark_size.setToolTip("Largura da marca d'água em % da largura do vídeo")
        self.watermark_opacity = QSpinBox(minimum=10, maximum=100, suffix=" %")
        form.addRow("Posição:", self.watermark_position)
        form.addRow("Tamanho:", self.watermark_size)
        form.addRow("Opacidade:", self.watermark_opacity)

        # -- Aplicar só a marca d'água num vídeo --------------------------- #
        form.addRow(self._section("🎬 Aplicar só a marca d'água num vídeo"))
        watermark_test_hint = QLabel(
            "Roda a edição agora mesmo, só com a marca d'água acima (sem "
            "gancho, barra de progresso, música ou narração) — não precisa "
            "ir até o Editor Simples pra testar."
        )
        watermark_test_hint.setObjectName("Muted")
        watermark_test_hint.setWordWrap(True)
        form.addRow("", watermark_test_hint)

        self.watermark_test_drop = DropArea()
        self.watermark_test_drop.setMinimumHeight(100)
        self.watermark_test_drop.fileSelected.connect(self._set_watermark_test_source)
        form.addRow("", self.watermark_test_drop)
        self.watermark_test_source_label = QLabel("Nenhum vídeo selecionado.")
        self.watermark_test_source_label.setObjectName("Muted")
        form.addRow("", self.watermark_test_source_label)

        self.watermark_test_button = QPushButton("🖼 Aplicar marca d'água")
        self.watermark_test_button.setEnabled(False)
        self.watermark_test_button.clicked.connect(self._apply_watermark_test)
        self.watermark_test_open_folder = QPushButton("📂 Abrir pasta")
        self.watermark_test_open_folder.setVisible(False)
        self.watermark_test_open_folder.clicked.connect(self._open_watermark_test_folder)
        test_actions = QWidget()
        test_actions_layout = QHBoxLayout(test_actions)
        test_actions_layout.setContentsMargins(0, 0, 0, 0)
        test_actions_layout.addWidget(self.watermark_test_button, stretch=1)
        test_actions_layout.addWidget(self.watermark_test_open_folder)
        form.addRow("", test_actions)

        self.watermark_test_progress = QProgressBar()
        self.watermark_test_progress.setRange(0, 0)
        self.watermark_test_progress.setTextVisible(False)
        self.watermark_test_progress.setVisible(False)
        form.addRow("", self.watermark_test_progress)
        self.watermark_test_status = QLabel("")
        self.watermark_test_status.setObjectName("Muted")
        form.addRow("", self.watermark_test_status)

        # -- Textos no vídeo ----------------------------------------------- #
        form.addRow(self._section("📝 Textos no vídeo"))
        self.hook_text = QLineEdit()
        self.hook_text.setPlaceholderText(
            "Ex.: O MELHOR MOMENTO DO EPISÓDIO 🔥 (fica fixo no topo; opcional)"
        )
        self.show_part_number = QCheckBox(
            'Mostrar "Parte X" nos cortes sequenciais (modo tempo fixo)'
        )
        form.addRow("Título/gancho:", self.hook_text)
        form.addRow("", self.show_part_number)

        # -- Barra de progresso -------------------------------------------- #
        form.addRow(self._section("📊 Barra de progresso"))
        self.progress_bar = QCheckBox(
            "Mostrar barra de progresso no rodapé do vídeo"
        )
        form.addRow("", self.progress_bar)

        # -- Volumes --------------------------------------------------------- #
        form.addRow(self._section("🔊 Volumes"))
        self.original_audio_volume = QSpinBox(minimum=0, maximum=200, suffix=" %")
        self.original_audio_volume.setToolTip(
            "Volume do áudio original do vídeo (100% = sem alteração)"
        )
        form.addRow("Áudio original do vídeo:", self.original_audio_volume)

        # -- Música de fundo ------------------------------------------------ #
        form.addRow(self._section("🎵 Música de fundo"))
        self.music_url = QLineEdit()
        self.music_url.setPlaceholderText("Cole o link do YouTube da música...")
        self.music_url.returnPressed.connect(self._download_music_from_youtube)
        self.music_download_btn = QPushButton("⬇ Baixar áudio")
        self.music_download_btn.clicked.connect(self._download_music_from_youtube)
        url_row = QWidget()
        url_layout = QHBoxLayout(url_row)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.addWidget(self.music_url, stretch=1)
        url_layout.addWidget(self.music_download_btn)
        form.addRow("Link do YouTube:", url_row)

        self.music_status = QLabel("")
        self.music_status.setObjectName("Muted")
        form.addRow("", self.music_status)

        self.music_path = QLineEdit()
        self.music_path.setReadOnly(True)
        self.music_path.setPlaceholderText(
            "Nenhuma música baixada (ou escolha um arquivo local abaixo)"
        )
        form.addRow("Arquivo atual:", self._file_row(self.music_path, self._pick_music))
        self.music_volume = QSpinBox(minimum=0, maximum=100, suffix=" %")
        self.music_volume.setToolTip("Volume da música em relação ao áudio original")
        form.addRow("Volume:", self.music_volume)

        # -- Narração por IA ------------------------------------------------ #
        form.addRow(self._section("🎙 Narração por IA (offline, ~10-12s por trecho — baixa o modelo na 1ª vez)"))
        self.tts_enabled = QCheckBox("Narrar um texto no início de cada short")
        self.tts_voice = QComboBox()
        for voice, label in C.TTS_VOICES.items():
            self.tts_voice.addItem(label, userData=voice)
        self.tts_text = QPlainTextEdit()
        self.tts_text.setPlaceholderText(
            "Escreva o texto que a IA vai narrar no começo de cada corte.\n"
            "Ex.: Se você gosta de anime, segue o canal pra não perder a parte 2!"
        )
        self.tts_text.setFixedHeight(90)
        form.addRow("", self.tts_enabled)
        form.addRow("Voz:", self.tts_voice)
        form.addRow("Texto:", self.tts_text)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch()
        save = QPushButton("💾 Salvar estilo")
        save.setObjectName("Primary")
        save.clicked.connect(self.save)
        footer.addWidget(save)
        outer.addLayout(footer)

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

    def _connect_autosave(self) -> None:
        """Salva automaticamente a cada mudança — sem precisar clicar em
        "Salvar estilo" nem redigitar tudo na próxima vez que abrir o app.

        Campos de texto usam um pequeno debounce (evita gravar a cada tecla);
        combos/checkboxes/spinboxes salvam na hora, já que mudam com pouca
        frequência.
        """
        def debounced(*_args) -> None:
            self._save_timer.start(500)

        for line_edit in (
            self.channel_name, self.channel_handle, self.channel_avatar,
            self.watermark_path, self.hook_text, self.music_path,
        ):
            line_edit.textChanged.connect(debounced)
        self.tts_text.textChanged.connect(debounced)
        self.watermark_path.textChanged.connect(
            lambda _t: self._refresh_watermark_test_enabled()
        )

        for combo in (
            self.badge_position, self.anime_framing, self.watermark_position,
            self.tts_voice,
        ):
            combo.currentIndexChanged.connect(lambda _i: self.save())

        for checkbox in (self.show_part_number, self.progress_bar, self.tts_enabled):
            checkbox.toggled.connect(lambda _c: self.save())

        for spinbox in (self.watermark_size, self.watermark_opacity, self.music_volume):
            spinbox.valueChanged.connect(debounced)

    # ------------------------------------------------------------------ #
    def _pick_watermark(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in C.SUPPORTED_IMAGE_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher marca d'água", "", f"Imagens ({patterns})",
        )
        if path:
            self.watermark_path.setText(path)

    def _pick_avatar(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in C.SUPPORTED_IMAGE_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher foto do canal", "", f"Imagens ({patterns})",
        )
        if path:
            self.channel_avatar.setText(path)

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
        self.channel_name.setText(s.channel_name)
        self.channel_handle.setText(s.channel_handle)
        self.channel_avatar.setText(s.channel_avatar_path)
        badge_index = self.badge_position.findData(s.channel_badge_position)
        self.badge_position.setCurrentIndex(max(badge_index, 0))
        framing_index = self.anime_framing.findData(s.anime_framing)
        self.anime_framing.setCurrentIndex(max(framing_index, 0))
        self.watermark_path.setText(s.watermark_path)
        index = self.watermark_position.findData(s.watermark_position)
        self.watermark_position.setCurrentIndex(max(index, 0))
        self.watermark_size.setValue(s.watermark_size)
        self.watermark_opacity.setValue(s.watermark_opacity)
        self.hook_text.setText(s.hook_text)
        self.show_part_number.setChecked(s.show_part_number)
        self.progress_bar.setChecked(s.progress_bar)
        self.original_audio_volume.setValue(s.original_audio_volume)
        self.music_path.setText(s.music_path)
        self.music_volume.setValue(s.music_volume)
        self.tts_enabled.setChecked(s.tts_enabled)
        voice_index = self.tts_voice.findData(s.tts_voice)
        self.tts_voice.setCurrentIndex(max(voice_index, 0))
        self.tts_text.setPlainText(s.tts_text)

    def save(self) -> None:
        """Grava o preset em Settings + config.json e regenera o selo."""
        s = self.settings
        s.channel_name = self.channel_name.text().strip()
        s.channel_handle = self.channel_handle.text().strip()
        s.channel_avatar_path = self.channel_avatar.text().strip()
        s.channel_badge_position = self.badge_position.currentData()
        s.anime_framing = self.anime_framing.currentData()
        if s.channel_name or s.channel_handle:
            from src.utils.badge import generate_badge

            generate_badge(
                s.channel_name, s.channel_handle, s.channel_avatar_path,
                C.CHANNEL_BADGE_FILE,
            )
        s.watermark_path = self.watermark_path.text().strip()
        s.watermark_position = self.watermark_position.currentData()
        s.watermark_size = self.watermark_size.value()
        s.watermark_opacity = self.watermark_opacity.value()
        s.hook_text = self.hook_text.text().strip()
        s.show_part_number = self.show_part_number.isChecked()
        s.progress_bar = self.progress_bar.isChecked()
        s.original_audio_volume = self.original_audio_volume.value()
        s.music_path = self.music_path.text().strip()
        s.music_volume = self.music_volume.value()
        s.tts_enabled = self.tts_enabled.isChecked()
        s.tts_voice = self.tts_voice.currentData()
        s.tts_text = self.tts_text.toPlainText().strip()
        s.save()
        logger.info("Estilo salvo.")

    # ------------------------------------------------------------------ #
    # Testar marca d'água num vídeo (edição isolada, sem os outros itens
    # do preset de Estilo — não passa pelo pipeline de cortes por IA).
    # ------------------------------------------------------------------ #
    def _set_watermark_test_source(self, source: str) -> None:
        self._test_source = source
        display = source if len(source) < 90 else source[:87] + "..."
        self.watermark_test_source_label.setText(f"🎞 {display}")
        self.watermark_test_open_folder.setVisible(False)
        self._refresh_watermark_test_enabled()

    def _refresh_watermark_test_enabled(self) -> None:
        has_watermark = bool(
            self.watermark_path.text().strip()
            and Path(self.watermark_path.text().strip()).exists()
        )
        self.watermark_test_button.setEnabled(
            has_watermark and self._test_source is not None and not self.is_running()
        )

    def _apply_watermark_test(self) -> None:
        if self._test_source is None:
            return
        self.save()  # garante que o preset (inclusive a marca d'água) está salvo
        s = self.settings
        options = EditOptions(
            watermark_path=s.watermark_path,
            watermark_position=s.watermark_position,
            watermark_size=s.watermark_size,
            watermark_opacity=s.watermark_opacity,
        )
        C.EDITOR_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stem = sanitize_filename(Path(self._test_source).stem)
        output_path = C.EDITOR_OUTPUT_DIR / f"{stem}_marca_dagua.mp4"

        self._test_worker = SimpleEditorWorker(
            self._test_source, output_path, options, use_gpu=s.use_gpu,
        )
        self._test_worker.progressChanged.connect(self._on_watermark_test_progress)
        self._test_worker.succeeded.connect(self._on_watermark_test_succeeded)
        self._test_worker.failed.connect(self._on_watermark_test_failed)
        self._test_worker.start()

        self.watermark_test_button.setEnabled(False)
        self.watermark_test_open_folder.setVisible(False)
        self.watermark_test_progress.setVisible(True)
        self.watermark_test_status.setText("Iniciando...")

    def _on_watermark_test_progress(self, message: str) -> None:
        self.watermark_test_status.setText(message)

    def _on_watermark_test_succeeded(self, output_path: str) -> None:
        self._test_last_output = output_path
        self.watermark_test_progress.setVisible(False)
        self.watermark_test_status.setText(f"Concluído: {output_path}")
        self.watermark_test_open_folder.setVisible(True)
        self._refresh_watermark_test_enabled()

    def _on_watermark_test_failed(self, message: str) -> None:
        self.watermark_test_progress.setVisible(False)
        self.watermark_test_status.setText("Erro ao aplicar marca d'água.")
        self._refresh_watermark_test_enabled()
        QMessageBox.warning(self, "Erro ao aplicar marca d'água", message)

    def _open_watermark_test_folder(self) -> None:
        if not self._test_last_output:
            return
        folder = str(Path(self._test_last_output).parent)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    # ------------------------------------------------------------------ #
    def is_running(self) -> bool:
        """Indica se há uma edição de teste em andamento (usado ao fechar a janela)."""
        return self._test_worker is not None and self._test_worker.isRunning()

    def wait_running_worker(self, timeout_ms: int) -> bool:
        """Aguarda o worker atual encerrar; True se terminou dentro do prazo."""
        if self._test_worker is None:
            return True
        return self._test_worker.wait(timeout_ms)

    def terminate_running_worker(self) -> None:
        """Força o encerramento do worker (último recurso, ao fechar o app)."""
        if self._test_worker is not None:
            self._test_worker.terminate()
            self._test_worker.wait(3000)
