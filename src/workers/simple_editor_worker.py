"""Worker QThread da aba Editor Simples: marca d'água + narração, sem cortes.

Roda `edit_video` em background para não travar a interface — a exportação
via FFmpeg é uma chamada bloqueante única (sem checkpoints), então este
worker não suporta pausar; apenas concluir, falhar ou ser aguardado.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from src.core.exceptions import AutoShortsError
from src.utils.logger import get_logger
from src.utils.paths import new_temp_dir
from src.video.simple_editor import EditOptions, edit_video

logger = get_logger("simple_editor_worker")


class SimpleEditorWorker(QThread):
    """Aplica a edição simples a um único vídeo em background."""

    progressChanged = Signal(str)   # mensagem de status
    succeeded = Signal(str)         # caminho do MP4 exportado
    failed = Signal(str)            # mensagem de erro amigável

    def __init__(
        self,
        source: str,
        output_path: str | Path,
        options: EditOptions,
        use_gpu: bool = True,
    ) -> None:
        super().__init__()
        self._source = source
        self._output_path = Path(output_path)
        self._options = options
        self._use_gpu = use_gpu

    def run(self) -> None:  # noqa: D102 - QThread entry point
        workdir = new_temp_dir("edit")
        try:
            edit_video(
                self._source, self._output_path, self._options, workdir,
                use_gpu=self._use_gpu,
                on_progress=self.progressChanged.emit,
            )
            self.succeeded.emit(str(self._output_path))
        except AutoShortsError as exc:
            logger.error("Erro na edição: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - nunca derrubar a aplicação
            logger.exception("Erro inesperado na edição.")
            self.failed.emit(f"Erro inesperado: {exc}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
