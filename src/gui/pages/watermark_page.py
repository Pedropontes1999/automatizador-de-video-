"""Página Remover Marca d'Água: apaga uma marca d'água estática (sempre na
mesma posição) de um vídeo, marcando a área numa pré-visualização de frame
dentro do próprio app.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.config import constants as C
from src.config.settings import Settings
from src.gui.widgets.drop_area import DropArea
from src.gui.widgets.frame_rect_selector import FrameRectSelector
from src.utils.logger import get_logger
from src.utils.paths import new_temp_dir, sanitize_filename
from src.video.watermark_remover import WatermarkRegion, extract_frame, render_text_cover
from src.workers.watermark_worker import WatermarkWorker

# Método usado quando a cobertura é imagem/texto: apaga a marca original
# (delogo) e cola a imagem/texto por cima, numa passada só — o combo mais
# confiável (some com a marca de qualquer jeito, sem depender só da
# reconstrução do delogo). O modo "blur" usa outro método (ver `_process`).
_METHOD = "remove_cover"

logger = get_logger("watermark_page")


def _fmt_clock(seconds: float) -> str:
    """Formata segundos como mm:ss.s."""
    minutes, secs = divmod(max(seconds, 0.0), 60)
    return f"{int(minutes):02d}:{secs:04.1f}"


class WatermarkPage(QWidget):
    """Tela de remoção de marca d'água estática."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._source: str | None = None
        self._region: tuple[int, int, int, int] | None = None
        self._frame_size: tuple[int, int] | None = None
        self._worker: WatermarkWorker | None = None
        self._last_output: str | None = None
        self._seeking = False
        self._build_ui()
        self._load_values()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        title = QLabel("Remover Marca d'Água")
        title.setObjectName("SectionTitle")
        outer.addWidget(title)
        subtitle = QLabel(
            "Envie um vídeo, carregue um frame, arraste um retângulo em cima "
            "da marca d'água e remova. Se a marca fica sempre no mesmo lugar "
            "(ex.: vários vídeos do mesmo canal), a última área marcada é "
            "reaproveitada automaticamente no próximo vídeo."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        self.drop_area = DropArea()
        self.drop_area.fileSelected.connect(self.set_source)
        outer.addWidget(self.drop_area)
        self.source_label = QLabel("Nenhum vídeo selecionado.")
        self.source_label.setObjectName("Muted")
        outer.addWidget(self.source_label)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        # -- Player: assista o vídeo pra achar onde a marca aparece --------- #
        content_layout.addWidget(self._section("▶ Assistir (ache o momento com a marca)"))
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(260)
        self.player.setVideoOutput(self.video_widget)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.errorOccurred.connect(self._on_player_error)
        content_layout.addWidget(self.video_widget)

        transport = QHBoxLayout()
        self.play_button = QPushButton("▶ Reproduzir")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self._toggle_play)
        self.time_label = QLabel("00:00.0 / 00:00.0")
        self.time_label.setObjectName("Muted")
        transport.addWidget(self.play_button)
        transport.addWidget(self.time_label)
        transport.addStretch()
        content_layout.addLayout(transport)

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.setEnabled(False)
        self.position_slider.sliderPressed.connect(self._on_slider_pressed)
        self.position_slider.sliderMoved.connect(self._on_slider_moved)
        self.position_slider.sliderReleased.connect(self._on_slider_released)
        content_layout.addWidget(self.position_slider)

        # -- Frame de referência ------------------------------------------- #
        content_layout.addWidget(self._section("🖼 Marcar a área da marca d'água"))
        frame_row = QHBoxLayout()
        self.load_frame_button = QPushButton("📸 Capturar frame no instante atual")
        self.load_frame_button.setEnabled(False)
        self.load_frame_button.clicked.connect(self._capture_current_frame)
        frame_row.addWidget(self.load_frame_button)
        frame_row.addStretch()
        content_layout.addLayout(frame_row)

        self.selector = FrameRectSelector()
        self.selector.regionChanged.connect(self._on_region_changed)
        content_layout.addWidget(self.selector)

        self.region_label = QLabel("Nenhuma área marcada.")
        self.region_label.setObjectName("Muted")
        content_layout.addWidget(self.region_label)

        # -- Cobertura (imagem própria, texto digitado ou só desfoque) ------- #
        content_layout.addWidget(self._section("🖼 Cobertura da marca d'água"))
        mode_row = QHBoxLayout()
        self.cover_mode_image = QRadioButton("🖼 Imagem")
        self.cover_mode_text = QRadioButton("🔤 Texto")
        self.cover_mode_blur = QRadioButton("🌫 Blur")
        self.cover_mode_group = QButtonGroup(self)
        self.cover_mode_group.addButton(self.cover_mode_image, 0)
        self.cover_mode_group.addButton(self.cover_mode_text, 1)
        self.cover_mode_group.addButton(self.cover_mode_blur, 2)
        self.cover_mode_image.setChecked(True)
        self.cover_mode_group.idClicked.connect(self._on_cover_mode_changed)
        mode_row.addWidget(self.cover_mode_image)
        mode_row.addWidget(self.cover_mode_text)
        mode_row.addWidget(self.cover_mode_blur)
        mode_row.addStretch()
        content_layout.addLayout(mode_row)

        self.cover_stack = QStackedWidget()

        image_page = QWidget()
        cover_row = QHBoxLayout(image_page)
        cover_row.setContentsMargins(0, 0, 0, 0)
        self.cover_image_path = QLineEdit()
        self.cover_image_path.setReadOnly(True)
        self.cover_image_path.setPlaceholderText(
            "Imagem pra cobrir a marca (ex.: logo do seu canal; pode ter "
            "fundo transparente)"
        )
        cover_choose = QPushButton("📂 Escolher...")
        cover_choose.clicked.connect(self._pick_cover_image)
        cover_clear = QPushButton("✖")
        cover_clear.setToolTip("Remover")
        cover_clear.setFixedWidth(36)
        cover_clear.clicked.connect(lambda: self.cover_image_path.setText(""))
        cover_row.addWidget(self.cover_image_path, stretch=1)
        cover_row.addWidget(cover_choose)
        cover_row.addWidget(cover_clear)
        self.cover_image_path.textChanged.connect(lambda _t: self._refresh_process_enabled())
        self.cover_stack.addWidget(image_page)

        text_page = QWidget()
        text_row = QHBoxLayout(text_page)
        text_row.setContentsMargins(0, 0, 0, 0)
        self.cover_text = QLineEdit()
        self.cover_text.setPlaceholderText(
            "Texto pra escrever em cima da marca (ex.: o nome do seu canal)"
        )
        self.cover_text.textChanged.connect(lambda _t: self._refresh_process_enabled())
        text_row.addWidget(self.cover_text, stretch=1)
        self.cover_stack.addWidget(text_page)

        blur_page = QWidget()
        blur_row = QHBoxLayout(blur_page)
        blur_row.setContentsMargins(0, 0, 0, 0)
        blur_info = QLabel("A área marcada será borrada — não precisa de imagem nem texto.")
        blur_info.setObjectName("Muted")
        blur_row.addWidget(blur_info)
        self.cover_stack.addWidget(blur_page)

        content_layout.addWidget(self.cover_stack)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        # -- Ações ------------------------------------------------------- #
        actions = QHBoxLayout()
        self.process_button = QPushButton("🧹🖼 Remover e cobrir marca d'água")
        self.process_button.setObjectName("Primary")
        self.process_button.setEnabled(False)
        self.process_button.clicked.connect(self._process)
        self.open_folder_button = QPushButton("📂 Abrir pasta")
        self.open_folder_button.setVisible(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        actions.addWidget(self.process_button, stretch=1)
        actions.addWidget(self.open_folder_button)
        outer.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminado: ffmpeg não reporta %
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        outer.addWidget(self.progress)
        self.status_label = QLabel("Pronto.")
        self.status_label.setObjectName("Muted")
        outer.addWidget(self.status_label)

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    # ------------------------------------------------------------------ #
    _COVER_MODES = ("image", "text", "blur")

    def _load_values(self) -> None:
        self.cover_image_path.setText(self.settings.watermark_cover_image_path)
        self.cover_text.setText(self.settings.watermark_cover_text)
        mode = self.settings.watermark_cover_mode
        index = self._COVER_MODES.index(mode) if mode in self._COVER_MODES else 0
        self.cover_mode_group.button(index).setChecked(True)
        self.cover_stack.setCurrentIndex(index)

    def _on_cover_mode_changed(self, mode_id: int) -> None:
        self.cover_stack.setCurrentIndex(mode_id)
        self._refresh_process_enabled()

    def _cover_mode(self) -> str:
        return self._COVER_MODES[self.cover_mode_group.checkedId()]

    def _pick_cover_image(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in C.SUPPORTED_IMAGE_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Escolher imagem de cobertura", "", f"Imagens ({patterns})",
        )
        if path:
            self.cover_image_path.setText(path)

    # ------------------------------------------------------------------ #
    # Fonte
    # ------------------------------------------------------------------ #
    def set_source(self, source: str) -> None:
        """Define o vídeo de origem, carrega no player e libera a marcação."""
        self._source = source
        display = source if len(source) < 90 else source[:87] + "..."
        self.source_label.setText(f"🎞 {display}")
        self.open_folder_button.setVisible(False)
        self.load_frame_button.setEnabled(True)
        self.play_button.setEnabled(True)
        self.position_slider.setEnabled(True)
        self.player.setSource(QUrl.fromLocalFile(source))
        self.status_label.setText("Pronto.")
        self._capture_frame_at(1.0)

    # ------------------------------------------------------------------ #
    # Player
    # ------------------------------------------------------------------ #
    def _toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText("⏸ Pausar" if playing else "▶ Reproduzir")

    def _on_duration_changed(self, duration_ms: int) -> None:
        self.position_slider.setRange(0, duration_ms)
        self._refresh_time_label()

    def _on_position_changed(self, position_ms: int) -> None:
        if not self._seeking:
            self.position_slider.setValue(position_ms)
        self._refresh_time_label()

    def _on_slider_pressed(self) -> None:
        self._seeking = True

    def _on_slider_moved(self, position_ms: int) -> None:
        self._refresh_time_label(position_ms)

    def _on_slider_released(self) -> None:
        self.player.setPosition(self.position_slider.value())
        self._seeking = False

    def _on_player_error(self, error: QMediaPlayer.Error, error_string: str) -> None:
        if error != QMediaPlayer.Error.NoError:
            logger.warning("Erro no player de vídeo: %s", error_string)
            self.status_label.setText(f"⚠ Não foi possível reproduzir: {error_string}")

    def _refresh_time_label(self, position_ms: int | None = None) -> None:
        pos = position_ms if position_ms is not None else self.player.position()
        total = self.player.duration()
        self.time_label.setText(f"{_fmt_clock(pos / 1000.0)} / {_fmt_clock(total / 1000.0)}")

    # ------------------------------------------------------------------ #
    # Marcação da área
    # ------------------------------------------------------------------ #
    def _capture_current_frame(self) -> None:
        """Captura o frame no instante em que o player está parado/pausado."""
        self._capture_frame_at(self.player.position() / 1000.0)

    def _capture_frame_at(self, timestamp: float) -> None:
        if self._source is None:
            return
        temp_dir = new_temp_dir("watermark")
        frame_path = temp_dir / "frame.png"
        try:
            extract_frame(self._source, timestamp, frame_path)
        except Exception as exc:  # noqa: BLE001 - erro de ffmpeg é amigável
            QMessageBox.warning(self, "Erro ao carregar frame", str(exc))
            return
        if not self.selector.load_frame(frame_path):
            QMessageBox.warning(self, "Erro ao carregar frame", "Frame inválido.")
            return
        self._frame_size = self.selector.frame_size()
        s = self.settings
        if s.watermark_region_w > 0 and s.watermark_region_h > 0:
            self.selector.set_region(
                s.watermark_region_x, s.watermark_region_y,
                s.watermark_region_w, s.watermark_region_h,
            )
            region = self.selector.region()
            if region is not None:
                self._on_region_changed(*region)

    def _on_region_changed(self, x: int, y: int, w: int, h: int) -> None:
        self._region = (x, y, w, h)
        self.region_label.setText(f"Área marcada: {w}x{h} px em ({x}, {y})")
        self._refresh_process_enabled()

    def _refresh_process_enabled(self) -> None:
        mode = self._cover_mode()
        if mode == "text":
            has_cover = bool(self.cover_text.text().strip())
        elif mode == "blur":
            has_cover = True
        else:
            has_cover = bool(self.cover_image_path.text().strip())
        ready = (
            self._source is not None and self._region is not None
            and has_cover and not self.is_running()
        )
        self.process_button.setEnabled(ready)

    # ------------------------------------------------------------------ #
    # Processamento
    # ------------------------------------------------------------------ #
    def is_running(self) -> bool:
        """Indica se há uma exportação em andamento (usado ao fechar a janela)."""
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

    def _process(self) -> None:
        if self._source is None or self._region is None:
            return
        x, y, w, h = self._region
        mode = self._cover_mode()
        s = self.settings

        cover_image: str | None = None
        if mode == "text":
            text = self.cover_text.text().strip()
            if not text:
                return
            temp_dir = new_temp_dir("watermark")
            try:
                cover_image = str(render_text_cover(text, w, h, temp_dir / "cover_text.png"))
            except Exception as exc:  # noqa: BLE001 - erro de fonte/PIL é amigável
                QMessageBox.warning(self, "Erro ao gerar texto de cobertura", str(exc))
                return
        elif mode == "image":
            cover_image = self.cover_image_path.text().strip()
            if not cover_image:
                return

        s.watermark_region_x, s.watermark_region_y = x, y
        s.watermark_region_w, s.watermark_region_h = w, h
        s.watermark_cover_mode = mode
        s.watermark_cover_image_path = self.cover_image_path.text().strip()
        s.watermark_cover_text = self.cover_text.text().strip()
        s.save()

        output_path = self._build_output_path(self._source)
        worker_method = "blur" if mode == "blur" else _METHOD
        self._worker = WatermarkWorker(
            self._source, output_path, WatermarkRegion(x, y, w, h),
            method=worker_method, cover_image=cover_image,
            use_gpu=s.use_gpu, crf=s.quality_crf, frame_size=self._frame_size,
        )
        self._worker.progressChanged.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

        self.process_button.setEnabled(False)
        self.open_folder_button.setVisible(False)
        self.progress.setVisible(True)
        self.status_label.setText("Iniciando...")

    @staticmethod
    def _build_output_path(source: str) -> Path:
        C.WATERMARK_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stem = sanitize_filename(Path(source).stem)
        return C.WATERMARK_OUTPUT_DIR / f"{stem}_sem_marca_coberto.mp4"

    def _on_progress(self, message: str) -> None:
        self.status_label.setText(message)

    def _on_succeeded(self, output_path: str) -> None:
        self._last_output = output_path
        self.progress.setVisible(False)
        self.status_label.setText(f"Concluído: {output_path}")
        self.open_folder_button.setVisible(True)
        self._refresh_process_enabled()
        QMessageBox.information(
            self, "Remoção e cobertura concluídas", f"Vídeo salvo em:\n{output_path}",
        )

    def _on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.status_label.setText("Erro ao remover/cobrir marca d'água.")
        self._refresh_process_enabled()
        QMessageBox.warning(self, "Erro ao remover/cobrir marca d'água", message)

    def _open_output_folder(self) -> None:
        if not self._last_output:
            return
        folder = str(Path(self._last_output).parent)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
