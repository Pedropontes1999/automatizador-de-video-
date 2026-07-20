"""Janela principal do AUTO SHORTS AI.

Estrutura: sidebar (esquerda) + QStackedWidget com as páginas
(Início, Dashboard, Histórico, Configurações). Gerencia o worker do
pipeline, a fila de tarefas e os atalhos globais.
"""
from __future__ import annotations

from collections import deque

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from src.config.constants import SUPPORTED_VIDEO_EXTENSIONS
from src.config.settings import Settings
from src.database.db import init_database
from src.gui.pages.dashboard_page import DashboardPage
from src.gui.pages.editor_page import EditorPage
from src.gui.pages.history_page import HistoryPage
from src.gui.pages.home_page import HomePage
from src.gui.pages.redub_page import RedubPage
from src.gui.pages.settings_page import SettingsPage
from src.gui.pages.simple_editor_page import SimpleEditorPage
from src.gui.pages.style_page import StylePage
from src.gui.theme import build_stylesheet
from src.gui.widgets.sidebar import Sidebar
from src.services.project_service import ProjectService
from src.utils.logger import get_logger
from src.workers.pipeline_worker import PipelineWorker
from src.workers.redub_worker import RedubWorker
from src.workers.video_editor_worker import VideoEditorWorker

logger = get_logger("main_window")


class MainWindow(QWidget):
    """Janela raiz da aplicação."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.service = ProjectService(settings)
        self.worker: PipelineWorker | None = None
        self.editor_worker: VideoEditorWorker | None = None
        self.redub_worker: RedubWorker | None = None
        self._queue: deque[str] = deque()  # fila de vídeos aguardando

        init_database()
        self._build_ui()
        self._create_shortcuts()
        self.setStyleSheet(build_stylesheet(settings.theme))
        self.setWindowTitle("AUTO SHORTS AI")
        self.resize(1280, 800)

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        """Monta sidebar + páginas."""
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar()
        root.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        self.home = HomePage()
        self.editor = EditorPage(self.settings)
        self.redub = RedubPage(self.settings)
        self.dashboard = DashboardPage()
        self.history = HistoryPage()
        self.simple_editor_page = SimpleEditorPage(self.settings)
        self.style_page = StylePage(self.settings)
        self.settings_page = SettingsPage(self.settings)
        for page in (self.home, self.editor, self.redub, self.dashboard,
                     self.history, self.simple_editor_page, self.style_page,
                     self.settings_page):
            self.pages.addWidget(page)
        root.addWidget(self.pages, stretch=1)

        # Navegação
        self.sidebar.pageSelected.connect(self.pages.setCurrentIndex)

        # Tipo de vídeo: restaura do config e persiste mudanças
        self.home.set_category(self.settings.video_category)
        self.home.set_anime_options(
            self.settings.anime_cut_mode, self.settings.anime_fixed_seconds,
        )
        self.home.categoryChanged.connect(self._on_category_changed)
        self.home.cutModeChanged.connect(self._on_cut_mode_changed)
        self.home.fixedDurationChanged.connect(self._on_fixed_duration_changed)

        # Legenda: restaura do config e persiste mudanças
        self.home.set_subtitle_enabled(self.settings.subtitles_enabled)
        self.home.subtitleToggled.connect(self._on_subtitle_toggled)

        # Fluxo de análise
        self.home.analyzeRequested.connect(self._enqueue_analysis)
        self.home.pauseRequested.connect(self._pause_worker)
        self.home.resumeRequested.connect(self._resume_worker)
        self.home.cancelRequested.connect(self._cancel_worker)

        # Fluxo do Editor de Vídeo
        self.editor.processRequested.connect(self._start_editor_worker)
        self.editor.pauseRequested.connect(self._pause_editor_worker)
        self.editor.resumeRequested.connect(self._resume_editor_worker)
        self.editor.cancelRequested.connect(self._cancel_editor_worker)

        # Fluxo da Redublagem
        self.redub.processRequested.connect(self._start_redub_worker)
        self.redub.pauseRequested.connect(self._pause_redub_worker)
        self.redub.resumeRequested.connect(self._resume_redub_worker)
        self.redub.cancelRequested.connect(self._cancel_redub_worker)

        # Tema dinâmico
        self.settings_page.themeChanged.connect(
            lambda theme: self.setStyleSheet(build_stylesheet(theme))
        )

    def _create_shortcuts(self) -> None:
        """Atalhos globais: Ctrl+O, Ctrl+S, Ctrl+Enter."""
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self._open_file_dialog)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._save_current_page)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.home.request_analyze)

    def _save_current_page(self) -> None:
        """Ctrl+S: salva a página aberta (Editor, Estilo ou Configurações)."""
        current = self.pages.currentWidget()
        if current is self.editor_page:
            self.editor_page.save()
        elif current is self.style_page:
            self.style_page.save()
        else:
            self.settings_page.save()

    def _on_category_changed(self, category: str) -> None:
        """Persiste o tipo de vídeo escolhido na Home."""
        self.settings.video_category = category
        self.settings.save()
        logger.info("Tipo de vídeo selecionado: %s", category)

    def _on_cut_mode_changed(self, mode: str) -> None:
        """Persiste o modo de corte do anime (ia | tempo)."""
        self.settings.anime_cut_mode = mode
        self.settings.save()
        logger.info("Modo de corte do anime: %s", mode)

    def _on_fixed_duration_changed(self, seconds: int) -> None:
        """Persiste a duração de cada corte no modo tempo fixo."""
        self.settings.anime_fixed_seconds = seconds
        self.settings.save()

    def _on_subtitle_toggled(self, enabled: bool) -> None:
        """Persiste se a legenda automática deve ser queimada no corte."""
        self.settings.subtitles_enabled = enabled
        self.settings.save()
        logger.info("Legenda automática %s.", "ativada" if enabled else "desativada")

    # ------------------------------------------------------------------ #
    # Fila e worker
    # ------------------------------------------------------------------ #
    def _any_worker_running(self, exclude: str = "") -> str | None:
        """Nome do processamento em andamento (cortes/editor/redub), se
        houver algum além de `exclude` — usado pra impedir dois workers
        pesados (CPU/GPU) rodando ao mesmo tempo."""
        candidates = (
            ("cortes", self.worker),
            ("edição de vídeo", self.editor_worker),
            ("redublagem", self.redub_worker),
        )
        for name, worker in candidates:
            if name != exclude and worker is not None and worker.isRunning():
                return name
        return None

    def _enqueue_analysis(self, source: str) -> None:
        """Adiciona o vídeo à fila; inicia imediatamente se ocioso."""
        blocking = self._any_worker_running(exclude="cortes")
        if blocking is not None:
            QMessageBox.warning(
                self, "Aguarde", f"Termine a {blocking} atual antes de gerar cortes.",
            )
            return
        if self.worker is not None and self.worker.isRunning():
            self._queue.append(source)
            logger.info("Vídeo adicionado à fila (%d aguardando).", len(self._queue))
            return
        self._start_worker(source)

    def _start_worker(self, source: str) -> None:
        """Cria e inicia o worker do pipeline para um vídeo."""
        self.worker = PipelineWorker(self.service, source)
        self.worker.progressChanged.connect(self._on_progress)
        self.worker.cutFinished.connect(self.home.add_cut_card)
        self.worker.projectFinished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.start()
        self.home.set_running(True)
        self.dashboard.set_status("Processando")
        logger.info("Processamento iniciado: %s", source)

    def _pause_worker(self) -> None:
        if self.worker is not None:
            self.worker.pause()
            self.dashboard.set_status("Pausado")
            logger.info("Processamento pausado.")

    def _resume_worker(self) -> None:
        if self.worker is not None:
            self.worker.resume_task()
            self.dashboard.set_status("Processando")
            logger.info("Processamento retomado.")

    def _cancel_worker(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.home.set_cancelling()
            self.dashboard.set_status("Cancelando...")
            logger.info(
                "Cancelamento solicitado — aguardando a etapa atual terminar."
            )

    # ------------------------------------------------------------------ #
    # Slots do worker (rodam na main thread)
    # ------------------------------------------------------------------ #
    def _on_progress(self, percent: int, message: str) -> None:
        self.home.update_progress(percent, message)

    def _on_finished(self, project) -> None:
        self.home.set_running(False)
        self.dashboard.set_status("Ocioso")
        self.dashboard.refresh_stats()
        self.history.reload()
        done = sum(1 for c in project.cuts if c.status == "done")
        QMessageBox.information(
            self, "Concluído",
            f"'{project.title}' finalizado!\n{done} cortes exportados para a pasta output/.",
        )
        self._process_next_in_queue()

    def _on_failed(self, message: str) -> None:
        self.home.set_running(False)
        self.home.update_progress(0, "Erro no processamento.")
        self.dashboard.set_status("Erro")
        QMessageBox.warning(self, "Erro no processamento", message)
        self._process_next_in_queue()

    def _on_cancelled(self) -> None:
        self.home.set_running(False)
        self.home.update_progress(0, "Cancelado.")
        self.dashboard.set_status("Ocioso")
        self._process_next_in_queue()

    def _process_next_in_queue(self) -> None:
        """Puxa o próximo vídeo da fila, se houver."""
        if self._queue:
            self._start_worker(self._queue.popleft())

    # ------------------------------------------------------------------ #
    # Editor de Vídeo (narração + estática de abertura, sem gerar Shorts)
    # ------------------------------------------------------------------ #
    def _start_editor_worker(self, source: str) -> None:
        """Cria e inicia o worker do Editor de Vídeo."""
        blocking = self._any_worker_running(exclude="edição de vídeo")
        if blocking is not None:
            QMessageBox.warning(
                self, "Aguarde", f"Termine a {blocking} atual antes de editar outro vídeo.",
            )
            return
        self.editor_worker = VideoEditorWorker(self.settings, source)
        self.editor_worker.progressChanged.connect(self.editor.update_progress)
        self.editor_worker.finished_ok.connect(self._on_edit_finished)
        self.editor_worker.failed.connect(self._on_edit_failed)
        self.editor_worker.cancelled.connect(self._on_edit_cancelled)
        self.editor_worker.start()
        self.editor.set_running(True)
        logger.info("Edição de vídeo iniciada: %s", source)

    def _pause_editor_worker(self) -> None:
        if self.editor_worker is not None:
            self.editor_worker.pause()
            logger.info("Edição de vídeo pausada.")

    def _resume_editor_worker(self) -> None:
        if self.editor_worker is not None:
            self.editor_worker.resume_task()
            logger.info("Edição de vídeo retomada.")

    def _cancel_editor_worker(self) -> None:
        if self.editor_worker is not None:
            self.editor_worker.cancel()
            self.editor.set_cancelling()
            logger.info(
                "Cancelamento da edição solicitado — aguardando a etapa atual terminar."
            )

    def _on_edit_finished(self, output_path: str) -> None:
        self.editor.set_running(False)
        QMessageBox.information(
            self, "Concluído", f"Vídeo editado salvo em:\n{output_path}",
        )

    def _on_edit_failed(self, message: str) -> None:
        self.editor.set_running(False)
        self.editor.update_progress(0, "Erro no processamento.")
        QMessageBox.warning(self, "Erro na edição", message)

    def _on_edit_cancelled(self) -> None:
        self.editor.set_running(False)
        self.editor.update_progress(0, "Cancelado.")

    # ------------------------------------------------------------------ #
    # Redublagem (troca a voz do narrador, mantendo música/efeitos)
    # ------------------------------------------------------------------ #
    def _start_redub_worker(self, source: str) -> None:
        """Cria e inicia o worker da Redublagem."""
        blocking = self._any_worker_running(exclude="redublagem")
        if blocking is not None:
            QMessageBox.warning(
                self, "Aguarde", f"Termine a {blocking} atual antes de redublar outro vídeo.",
            )
            return
        self.redub_worker = RedubWorker(self.settings, source)
        self.redub_worker.progressChanged.connect(self.redub.update_progress)
        self.redub_worker.finished_ok.connect(self._on_redub_finished)
        self.redub_worker.failed.connect(self._on_redub_failed)
        self.redub_worker.cancelled.connect(self._on_redub_cancelled)
        self.redub_worker.start()
        self.redub.set_running(True)
        logger.info("Redublagem iniciada: %s", source)

    def _pause_redub_worker(self) -> None:
        if self.redub_worker is not None:
            self.redub_worker.pause()
            logger.info("Redublagem pausada.")

    def _resume_redub_worker(self) -> None:
        if self.redub_worker is not None:
            self.redub_worker.resume_task()
            logger.info("Redublagem retomada.")

    def _cancel_redub_worker(self) -> None:
        if self.redub_worker is not None:
            self.redub_worker.cancel()
            self.redub.set_cancelling()
            logger.info(
                "Cancelamento da redublagem solicitado — aguardando a etapa atual terminar."
            )

    def _on_redub_finished(self, output_path: str) -> None:
        self.redub.set_running(False)
        QMessageBox.information(
            self, "Concluído", f"Vídeo redublado salvo em:\n{output_path}",
        )

    def _on_redub_failed(self, message: str) -> None:
        self.redub.set_running(False)
        self.redub.update_progress(0, "Erro no processamento.")
        QMessageBox.warning(self, "Erro na redublagem", message)

    def _on_redub_cancelled(self) -> None:
        self.redub.set_running(False)
        self.redub.update_progress(0, "Cancelado.")

    # ------------------------------------------------------------------ #
    def _open_file_dialog(self) -> None:
        """Atalho Ctrl+O: seleciona vídeo diretamente."""
        patterns = " ".join(f"*{ext}" for ext in SUPPORTED_VIDEO_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar vídeo", "", f"Vídeos ({patterns})",
        )
        if path:
            self.home.set_source(path)
            self.pages.setCurrentIndex(0)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """Garante que os workers são finalizados antes de fechar."""
        active = next(
            (w for w in (self.worker, self.editor_worker, self.redub_worker)
             if w is not None and w.isRunning()),
            None,
        )
        if active is not None:
            answer = QMessageBox.question(
                self, "Sair",
                "Há um processamento em andamento. Cancelar e sair?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            active.cancel()
            # Espera o worker encerrar de forma limpa; se uma etapa longa
            # (ex.: Whisper, reencode do vídeo) não responder, termina à
            # força para nunca crashar com "QThread destroyed while running".
            if not active.wait(8000):
                logger.warning("Worker não respondeu ao cancelamento; terminando.")
                active.terminate()
                active.wait(3000)

        if self.simple_editor_page.is_running():
            answer = QMessageBox.question(
                self, "Sair",
                "Há uma edição de vídeo em andamento. Cancelar e sair?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            # A exportação via FFmpeg não é cancelável no meio (chamada
            # bloqueante única); espera terminar e força se necessário.
            if not self.simple_editor_page.wait_running_worker(8000):
                logger.warning("Edição não respondeu ao fechar; terminando.")
                self.simple_editor_page.terminate_running_worker()
        event.accept()
