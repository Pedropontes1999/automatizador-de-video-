"""Página Cortar Vídeo: pré-visualização com player + linha do tempo dentro
do próprio app, marcação manual de trechos a remover (em segundos exatos) e
exportação de todos os cortes pendentes de uma vez.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.config import constants as C
from src.config.settings import Settings
from src.gui.widgets.drop_area import DropArea
from src.gui.widgets.trim_range_row import TrimRangeRow
from src.utils.logger import get_logger
from src.utils.paths import sanitize_filename
from src.video.trim_editor import CutRange
from src.workers.trim_worker import TrimWorker

logger = get_logger("trim_page")


def _fmt_clock(seconds: float) -> str:
    """Formata segundos como mm:ss.s."""
    minutes, secs = divmod(max(seconds, 0.0), 60)
    return f"{int(minutes):02d}:{secs:04.1f}"


class TrimPage(QWidget):
    """Player de vídeo + marcação manual de cortes, tudo dentro do app."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._source: str | None = None
        self._cuts: list[CutRange] = []
        self._worker: TrimWorker | None = None
        self._last_output: str | None = None
        self._seeking = False
        self._build_ui()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        title = QLabel("Cortar Vídeo")
        title.setObjectName("SectionTitle")
        outer.addWidget(title)
        subtitle = QLabel(
            "Assista ao vídeo dentro do app, marque os trechos que quer remover "
            "(ex.: do segundo 17 ao 18) e aplique todos de uma vez. O original "
            "nunca é sobrescrito — sai um novo arquivo em output/cortados/."
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

        # -- Player -------------------------------------------------------- #
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(320)
        self.player.setVideoOutput(self.video_widget)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.errorOccurred.connect(self._on_player_error)
        content_layout.addWidget(self.video_widget, stretch=1)

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
        self.position_slider.sliderReleased.connect(self._on_slider_released)
        self.position_slider.sliderMoved.connect(self._on_slider_moved)
        content_layout.addWidget(self.position_slider)

        # -- Marcação de corte ---------------------------------------------- #
        content_layout.addWidget(self._section("✂ Marcar trecho a remover"))
        mark_row = QHBoxLayout()
        self.start_spin = QDoubleSpinBox(minimum=0, maximum=999999, decimals=2, suffix=" s")
        self.end_spin = QDoubleSpinBox(minimum=0, maximum=999999, decimals=2, suffix=" s")
        mark_start_btn = QPushButton("🎯 Início = posição atual")
        mark_start_btn.clicked.connect(self._mark_start)
        mark_end_btn = QPushButton("🎯 Fim = posição atual")
        mark_end_btn.clicked.connect(self._mark_end)
        mark_row.addWidget(QLabel("Início:"))
        mark_row.addWidget(self.start_spin)
        mark_row.addWidget(mark_start_btn)
        mark_row.addSpacing(16)
        mark_row.addWidget(QLabel("Fim:"))
        mark_row.addWidget(self.end_spin)
        mark_row.addWidget(mark_end_btn)
        content_layout.addLayout(mark_row)

        self.add_cut_button = QPushButton("+ Adicionar corte à lista")
        self.add_cut_button.setEnabled(False)
        self.add_cut_button.clicked.connect(self._add_cut)
        content_layout.addWidget(self.add_cut_button)

        content_layout.addWidget(self._section("🗒 Cortes pendentes"))
        self.cuts_container = QVBoxLayout()
        self.cuts_container.setSpacing(6)
        cuts_widget = QWidget()
        cuts_widget.setLayout(self.cuts_container)
        content_layout.addWidget(cuts_widget)
        self._rebuild_cuts_list()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        # -- Ações ----------------------------------------------------------- #
        actions = QHBoxLayout()
        self.apply_button = QPushButton("✂ Aplicar cortes")
        self.apply_button.setObjectName("Primary")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply_cuts)
        self.open_folder_button = QPushButton("📂 Abrir pasta")
        self.open_folder_button.setVisible(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        actions.addWidget(self.apply_button, stretch=1)
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
    # Fonte / player
    # ------------------------------------------------------------------ #
    def set_source(self, source: str) -> None:
        """Carrega o vídeo no player e reseta os cortes pendentes."""
        self._source = source
        display = source if len(source) < 90 else source[:87] + "..."
        self.source_label.setText(f"🎞 {display}")
        self.open_folder_button.setVisible(False)
        self._clear_cuts()
        self.player.setSource(QUrl.fromLocalFile(source))
        self.play_button.setEnabled(True)
        self.position_slider.setEnabled(True)
        self.add_cut_button.setEnabled(True)
        self.status_label.setText("Pronto.")

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
        seconds = duration_ms / 1000.0
        self.start_spin.setMaximum(max(seconds, 0.0))
        self.end_spin.setMaximum(max(seconds, 0.0))
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
    # Marcação e lista de cortes
    # ------------------------------------------------------------------ #
    def _mark_start(self) -> None:
        self.start_spin.setValue(self.player.position() / 1000.0)

    def _mark_end(self) -> None:
        self.end_spin.setValue(self.player.position() / 1000.0)

    def _add_cut(self) -> None:
        start, end = self.start_spin.value(), self.end_spin.value()
        if end <= start:
            QMessageBox.warning(
                self, "Intervalo inválido", "O fim deve ser maior que o início.",
            )
            return
        self._cuts.append(CutRange(start, end))
        self._cuts.sort(key=lambda c: c.start)
        self._rebuild_cuts_list()
        self._refresh_apply_enabled()

    def _remove_cut(self, cut: CutRange) -> None:
        self._cuts.remove(cut)
        self._rebuild_cuts_list()
        self._refresh_apply_enabled()

    def _clear_cuts(self) -> None:
        self._cuts.clear()
        self._rebuild_cuts_list()
        self._refresh_apply_enabled()

    def _rebuild_cuts_list(self) -> None:
        while self.cuts_container.count():
            item = self.cuts_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._cuts:
            empty_label = QLabel("Nenhum corte adicionado ainda.")
            empty_label.setObjectName("Muted")
            self.cuts_container.addWidget(empty_label)
            return
        for cut in self._cuts:
            row = TrimRangeRow(cut)
            row.removeRequested.connect(self._remove_cut)
            self.cuts_container.addWidget(row)

    def _refresh_apply_enabled(self) -> None:
        self.apply_button.setEnabled(
            self._source is not None and bool(self._cuts) and not self.is_running()
        )

    # ------------------------------------------------------------------ #
    # Aplicação dos cortes
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

    def _apply_cuts(self) -> None:
        if self._source is None or not self._cuts:
            return
        self.player.pause()
        output_path = self._build_output_path(self._source)
        self._worker = TrimWorker(
            self._source, output_path, list(self._cuts), use_gpu=self.settings.use_gpu,
        )
        self._worker.progressChanged.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

        self.apply_button.setEnabled(False)
        self.open_folder_button.setVisible(False)
        self.progress.setVisible(True)
        self.status_label.setText("Iniciando...")

    @staticmethod
    def _build_output_path(source: str) -> Path:
        C.TRIM_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        stem = sanitize_filename(Path(source).stem)
        return C.TRIM_OUTPUT_DIR / f"{stem}_cortado.mp4"

    def _on_progress(self, message: str) -> None:
        self.status_label.setText(message)

    def _on_succeeded(self, output_path: str) -> None:
        self._last_output = output_path
        self.progress.setVisible(False)
        self.status_label.setText(f"Concluído: {output_path}")
        self.open_folder_button.setVisible(True)
        self._refresh_apply_enabled()
        QMessageBox.information(
            self, "Corte concluído", f"Vídeo salvo em:\n{output_path}",
        )

    def _on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.status_label.setText("Erro ao cortar.")
        self._refresh_apply_enabled()
        QMessageBox.warning(self, "Erro ao cortar vídeo", message)

    def _open_output_folder(self) -> None:
        if not self._last_output:
            return
        folder = str(Path(self._last_output).parent)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
