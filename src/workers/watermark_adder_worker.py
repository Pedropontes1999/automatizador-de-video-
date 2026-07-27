"""Worker QThread da aba Marca d'Água: aplica imagem/texto em background.

Chamada bloqueante única (sem checkpoints), assim como o Editor Simples —
não há suporte a pausar, só concluir, falhar ou ser aguardado.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from src.core.exceptions import AutoShortsError
from src.utils.logger import get_logger
from src.utils.paths import new_temp_dir
from src.video.watermark_adder import WatermarkAddOptions, add_watermark

logger = get_logger("watermark_adder_worker")


class WatermarkAdderWorker(QThread):
    """Aplica a marca d'água a um único vídeo em background."""

    progressChanged = Signal(str)   # mensagem de status
    succeeded = Signal(str)         # caminho do MP4 exportado
    failed = Signal(str)            # mensagem de erro amigável

    def __init__(
        self,
        source: str,
        output_path: str | Path,
        options: WatermarkAddOptions,
        use_gpu: bool = True,
    ) -> None:
        super().__init__()
        self._source = source
        self._output_path = Path(output_path)
        self._options = options
        self._use_gpu = use_gpu

    def run(self) -> None:  # noqa: D102 - QThread entry point
        workdir = new_temp_dir("watermark_add")
        try:
            add_watermark(
                self._source, self._output_path, self._options, workdir,
                use_gpu=self._use_gpu,
                on_progress=self.progressChanged.emit,
            )
            self.succeeded.emit(str(self._output_path))
        except AutoShortsError as exc:
            logger.error("Erro ao aplicar marca d'água: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - nunca derrubar a aplicação
            logger.exception("Erro inesperado ao aplicar marca d'água.")
            self.failed.emit(f"Erro inesperado: {exc}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
