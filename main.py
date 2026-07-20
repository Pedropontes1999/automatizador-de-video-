"""AUTO SHORTS AI - Ponto de entrada da aplicação.

Transforma vídeos longos em vários Shorts automaticamente usando IA local
(Whisper + Ollama + OpenCV + FFmpeg). 100% gratuito e offline.

Uso:
    python main.py
"""
from __future__ import annotations

import os
import sys
import traceback

# Rodando via pythonw.exe (sem console), sys.stdout/stderr vêm como None.
# Bibliotecas que escrevem barras de progresso nesses streams (ex.: tqdm no
# download de modelos do Whisper) quebram com AttributeError. Redireciona
# para os.devnull antes de qualquer import que possa usá-los.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from PySide6.QtWidgets import QApplication, QMessageBox

from src.config.settings import Settings
from src.utils.logger import get_logger
from src.utils.paths import ensure_project_folders

logger = get_logger("main")


def _global_exception_hook(exc_type, exc_value, exc_tb) -> None:
    """Captura qualquer exceção não tratada para nunca fechar a aplicação
    inesperadamente. Loga o erro e mostra um diálogo amigável."""
    message = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical("Exceção não tratada:\n%s", message)
    try:
        QMessageBox.critical(
            None,
            "AUTO SHORTS AI - Erro",
            "Ocorreu um erro inesperado. A aplicação continuará aberta.\n\n"
            f"{exc_value}\n\nDetalhes salvos em logs/.",
        )
    except Exception:  # noqa: BLE001 - GUI pode não estar disponível
        pass


def main() -> int:
    """Inicializa pastas, configurações, banco e a interface gráfica."""
    ensure_project_folders()

    # Garante que o FFmpeg seja encontrado mesmo se o PATH do Windows ainda
    # não foi atualizado nesta sessão (ex.: app aberta logo após instalar).
    from src.utils.ffmpeg_utils import ensure_ffmpeg_in_path

    ensure_ffmpeg_in_path()
    settings = Settings.load()

    app = QApplication(sys.argv)
    app.setApplicationName("AUTO SHORTS AI")
    app.setOrganizationName("AutoShortsAI")

    sys.excepthook = _global_exception_hook

    # Import tardio: a GUI depende do QApplication já existir.
    from src.gui.main_window import MainWindow

    window = MainWindow(settings)
    window.show()

    logger.info("Aplicação iniciada.")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
