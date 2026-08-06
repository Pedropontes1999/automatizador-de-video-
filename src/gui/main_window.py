"""Janela principal do AUTO SHORTS AI.

Estrutura: sidebar (esquerda) + QStackedWidget com as 4 páginas mantidas na
navegação — Editar Shorts (remoção de marca d'água + Modo Humanizado),
Download, Redublagem e Marca d'Água (adiciona imagem/texto sobre um vídeo).
As demais páginas do projeto (Início/cortes por IA, Dashboard, Histórico,
Transcrição, Editor, Editor Simples, Cortar Vídeo, Estilo, Configurações)
continuam existindo no código, só não estão conectadas na navegação — por
pedido do usuário em 2026-07, pra simplificar o app ao fluxo que ele
realmente usa.
"""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QStackedWidget, QWidget

from src.config.settings import Settings
from src.gui.pages.download_page import DownloadPage
from src.gui.pages.redub_page import RedubPage
from src.gui.pages.watermark_add_page import WatermarkAddPage
from src.gui.pages.watermark_page import WatermarkPage
from src.gui.theme import build_stylesheet
from src.gui.widgets.sidebar import Sidebar
from src.utils.logger import get_logger
from src.workers.redub_worker import (
    RedubGenerateWorker,
    RedubPrepareWorker,
    RedubTranslateWorker,
)
from src.workers.voice_preview_worker import VoicePreviewWorker

logger = get_logger("main_window")


class _CurrentPageStack(QStackedWidget):
    """QStackedWidget cujo tamanho mínimo segue só a página visível.

    Por padrão o Qt calcula o minimumSizeHint como o maior entre TODAS as
    páginas já adicionadas (mesmo as escondidas), então uma página alta
    travava a altura mínima da janela mesmo com uma página menor
    selecionada. Sobrescrevendo aqui, cada página passa a controlar sua
    própria altura mínima.
    """

    def sizeHint(self):  # noqa: N802 (Qt API)
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):  # noqa: N802 (Qt API)
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()


class MainWindow(QWidget):
    """Janela raiz da aplicação."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.redub_worker: RedubPrepareWorker | RedubGenerateWorker | None = None
        self.redub_translate_worker: RedubTranslateWorker | None = None
        self._redub_preparation = None  # RedubPreparation da última transcrição (etapa 1)
        self.voice_preview_worker: VoicePreviewWorker | None = None
        self._voice_preview_requester: RedubPage | None = None  # página que pediu o teste
        self._voice_preview_audio_output = QAudioOutput(self)
        self._voice_preview_player = QMediaPlayer(self)
        self._voice_preview_player.setAudioOutput(self._voice_preview_audio_output)

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

        self.pages = _CurrentPageStack()
        self.pages.currentChanged.connect(lambda _i: self.pages.updateGeometry())
        self.watermark_page = WatermarkPage(self.settings)
        self.download_page = DownloadPage()
        self.redub = RedubPage(self.settings)
        self.watermark_add_page = WatermarkAddPage(self.settings)
        for page in (self.watermark_page, self.download_page, self.redub, self.watermark_add_page):
            self.pages.addWidget(page)
        root.addWidget(self.pages, stretch=1)

        # Navegação
        self.sidebar.pageSelected.connect(self.pages.setCurrentIndex)
        self.download_page.openInEditor.connect(self._open_in_watermark_page)

        # Fluxo da Redublagem (2 etapas: transcrever, depois gerar a nova voz)
        self.redub.transcribeRequested.connect(self._start_redub_prepare)
        self.redub.translateRequested.connect(self._start_redub_translate)
        self.redub.generateRequested.connect(self._start_redub_generate)
        self.redub.pauseRequested.connect(self._pause_redub_worker)
        self.redub.resumeRequested.connect(self._resume_redub_worker)
        self.redub.cancelRequested.connect(self._cancel_redub_worker)
        self.redub.previewVoiceRequested.connect(
            lambda voice: self._start_voice_preview(self.redub, voice)
        )
        self.redub.replayVoicePreviewRequested.connect(self._replay_voice_preview)

    def _create_shortcuts(self) -> None:
        """Atalho global: Ctrl+S salva a página aberta."""
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._save_current_page)

    def _save_current_page(self) -> None:
        """Ctrl+S: só a Redublagem tem opções persistidas em Settings; as
        outras duas páginas processam na hora, sem formulário pra salvar."""
        if self.pages.currentWidget() is self.redub:
            self.redub.save()

    def _open_in_watermark_page(self, video_path: str) -> None:
        """Manda um vídeo baixado direto pra Editar Shorts, já selecionado."""
        self.watermark_page.set_source(video_path)
        self.pages.setCurrentIndex(self.pages.indexOf(self.watermark_page))
        self.sidebar.set_current_index(self.pages.indexOf(self.watermark_page))

    # ------------------------------------------------------------------ #
    # Redublagem (troca a voz do narrador, mantendo música/efeitos)
    # ------------------------------------------------------------------ #
    def _any_worker_running(self, exclude: str = "") -> str | None:
        """Nome do processamento em andamento (redublagem), se houver algum
        além de `exclude` — usado pra impedir dois workers pesados (CPU/GPU)
        rodando ao mesmo tempo."""
        worker = self.redub_worker or self.redub_translate_worker
        if exclude != "redublagem" and worker is not None and worker.isRunning():
            return "redublagem"
        if (
            exclude != "teste de voz"
            and self.voice_preview_worker is not None
            and self.voice_preview_worker.isRunning()
        ):
            return "teste de voz"
        return None

    def _start_redub_prepare(self, source: str) -> None:
        """Etapa 1: cria e inicia o worker de transcrição da Redublagem."""
        blocking = self._any_worker_running(exclude="redublagem")
        if blocking is not None:
            QMessageBox.warning(
                self, "Aguarde", f"Termine a {blocking} atual antes de redublar outro vídeo.",
            )
            return
        self._redub_preparation = None
        self.redub_worker = RedubPrepareWorker(self.settings, source)
        self.redub_worker.progressChanged.connect(self.redub.update_progress)
        self.redub_worker.succeeded.connect(self._on_redub_prepared)
        self.redub_worker.failed.connect(self._on_redub_failed)
        self.redub_worker.cancelled.connect(self._on_redub_cancelled)
        self.redub_worker.start()
        self.redub.set_running(True)
        logger.info("Transcrição da redublagem iniciada: %s", source)

    def _on_redub_prepared(self, preparation) -> None:
        """Etapa 1 concluída: mostra o texto original pro usuário reescrever."""
        self.redub_worker = None
        self._redub_preparation = preparation
        self.redub.set_running(False)
        texts = [seg.text.strip() for seg in preparation.segments]
        self.redub.show_transcription(texts)
        self.redub.update_progress(100, "Transcrição pronta — revise o texto e gere a nova voz.")

    def _start_redub_translate(self, texts: list[str]) -> None:
        """Etapa 1.5 (opcional): traduz o texto revisado para PT-BR via
        Ollama, antes da geração da nova voz — usado quando o vídeo
        original está em outro idioma."""
        blocking = self._any_worker_running(exclude="redublagem")
        if blocking is not None:
            QMessageBox.warning(
                self, "Aguarde", f"Termine a {blocking} atual antes de traduzir.",
            )
            return
        self.redub_translate_worker = RedubTranslateWorker(self.settings, texts)
        self.redub_translate_worker.progressChanged.connect(self.redub.update_progress)
        self.redub_translate_worker.succeeded.connect(self._on_redub_translated)
        self.redub_translate_worker.failed.connect(self._on_redub_translate_failed)
        self.redub_translate_worker.start()
        self.redub.set_translating(True)
        logger.info("Tradução da redublagem para PT-BR iniciada (%d trecho(s)).", len(texts))

    def _on_redub_translated(self, texts: list[str]) -> None:
        self.redub_translate_worker = None
        self.redub.set_translating(False)
        self.redub.apply_translation(texts)
        self.redub.update_progress(100, "Tradução concluída — revise o texto antes de gerar a voz.")

    def _on_redub_translate_failed(self, message: str) -> None:
        self.redub_translate_worker = None
        self.redub.set_translating(False)
        self.redub.update_progress(0, "Erro na tradução.")
        QMessageBox.warning(self, "Erro na tradução", message)

    def _start_redub_generate(self, texts: list[str]) -> None:
        """Etapa 2: gera a nova narração a partir do texto revisado pelo usuário."""
        if self._redub_preparation is None:
            QMessageBox.warning(
                self, "Transcreva primeiro",
                "Transcreva o vídeo (etapa 1) antes de gerar a nova narração.",
            )
            return
        blocking = self._any_worker_running(exclude="redublagem")
        if blocking is not None:
            QMessageBox.warning(
                self, "Aguarde", f"Termine a {blocking} atual antes de gerar a redublagem.",
            )
            return
        self.redub_worker = RedubGenerateWorker(self.settings, self._redub_preparation, texts)
        self.redub_worker.progressChanged.connect(self.redub.update_progress)
        self.redub_worker.finished_ok.connect(self._on_redub_finished)
        self.redub_worker.failed.connect(self._on_redub_failed)
        self.redub_worker.cancelled.connect(self._on_redub_cancelled)
        self.redub_worker.start()
        self.redub.set_running(True)
        logger.info("Geração da nova narração (redublagem) iniciada.")

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
        self.redub_worker = None
        self.redub.set_running(False)
        QMessageBox.information(
            self, "Concluído", f"Vídeo redublado salvo em:\n{output_path}",
        )

    def _on_redub_failed(self, message: str) -> None:
        self.redub_worker = None
        self.redub.set_running(False)
        self.redub.update_progress(0, "Erro no processamento.")
        QMessageBox.warning(self, "Erro na redublagem", message)

    def _on_redub_cancelled(self) -> None:
        self.redub_worker = None
        self.redub.set_running(False)
        self.redub.update_progress(0, "Cancelado.")

    # ------------------------------------------------------------------ #
    # Teste de voz (botão "Testar voz" da Redublagem)
    # ------------------------------------------------------------------ #
    def _start_voice_preview(self, page: RedubPage, voice: str) -> None:
        blocking = self._any_worker_running(exclude="teste de voz")
        if blocking is not None:
            QMessageBox.warning(
                self, "Aguarde", f"Termine a {blocking} atual antes de testar uma voz.",
            )
            return
        self._voice_preview_requester = page
        page.set_preview_running(True)
        self.voice_preview_worker = VoicePreviewWorker(self.settings, voice)
        self.voice_preview_worker.succeeded.connect(self._on_voice_preview_ready)
        self.voice_preview_worker.failed.connect(self._on_voice_preview_failed)
        self.voice_preview_worker.start()
        logger.info("Teste de voz iniciado (%s).", voice)

    def _on_voice_preview_ready(self, path: str) -> None:
        self.voice_preview_worker = None
        page, self._voice_preview_requester = self._voice_preview_requester, None
        if page is not None:
            page.set_preview_running(False)
            page.set_preview_ready()
        self._voice_preview_player.setSource(QUrl.fromLocalFile(path))
        self._voice_preview_player.play()

    def _replay_voice_preview(self) -> None:
        """Toca de novo o último teste de voz já gerado (sem sintetizar de novo)."""
        if not self._voice_preview_player.source().isEmpty():
            self._voice_preview_player.setPosition(0)
            self._voice_preview_player.play()

    def _on_voice_preview_failed(self, message: str) -> None:
        self.voice_preview_worker = None
        page, self._voice_preview_requester = self._voice_preview_requester, None
        if page is not None:
            page.set_preview_running(False)
        QMessageBox.warning(self, "Erro no teste de voz", message)

    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """Garante que os workers são finalizados antes de fechar."""
        active = next(
            (w for w in (self.redub_worker, self.redub_translate_worker)
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

        if self.voice_preview_worker is not None and self.voice_preview_worker.isRunning():
            # Sem etapa de cancelamento (é uma síntese curta e única) — só
            # espera terminar ou força, igual aos outros workers acima.
            if not self.voice_preview_worker.wait(8000):
                self.voice_preview_worker.terminate()
                self.voice_preview_worker.wait(3000)

        if self.watermark_page.is_running():
            answer = QMessageBox.question(
                self, "Sair",
                "Há uma remoção de marca d'água em andamento. Cancelar e sair?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if not self.watermark_page.wait_running_worker(8000):
                logger.warning("Remoção não respondeu ao fechar; terminando.")
                self.watermark_page.terminate_running_worker()

        if self.download_page.is_running():
            answer = QMessageBox.question(
                self, "Sair",
                "Há um download em andamento. Cancelar e sair?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if not self.download_page.wait_running_worker(8000):
                logger.warning("Download não respondeu ao fechar; terminando.")
                self.download_page.terminate_running_worker()

        if self.watermark_add_page.is_running():
            answer = QMessageBox.question(
                self, "Sair",
                "Há uma marca d'água sendo aplicada. Cancelar e sair?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if not self.watermark_add_page.wait_running_worker(8000):
                logger.warning("Marca d'água não respondeu ao fechar; terminando.")
                self.watermark_add_page.terminate_running_worker()
        event.accept()
