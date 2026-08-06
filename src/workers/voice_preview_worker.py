"""Worker QThread que sintetiza um trecho curto pra tocar no app (botão
"Testar voz" da Redublagem) sem precisar rodar nenhum pipeline completo.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.audio.tts import synthesize
from src.config import constants as C
from src.config.settings import Settings
from src.utils.logger import get_logger
from src.utils.paths import new_temp_dir

logger = get_logger("voice_preview_worker")


class VoicePreviewWorker(QThread):
    """Sintetiza `C.VOICE_PREVIEW_TEXT` com a voz escolhida, em background."""

    succeeded = Signal(str)   # caminho do WAV gerado
    failed = Signal(str)      # mensagem de erro amigável

    def __init__(self, settings: Settings, voice: str) -> None:
        super().__init__()
        self._settings = settings
        self._voice = voice

    def run(self) -> None:  # noqa: D102 - QThread entry point
        s = self._settings
        try:
            workdir = new_temp_dir("voice_preview")
            path = synthesize(
                C.VOICE_PREVIEW_TEXT, self._voice, workdir / "preview.mp3",
                api_key=s.elevenlabs_api_key,
                reference_audio=s.chatterbox_reference_path,
                use_gpu=s.use_gpu,
            )
            if path is None:
                self.failed.emit("Não foi possível gerar o teste dessa voz (veja o log).")
                return
            self.succeeded.emit(str(path))
        except Exception as exc:  # noqa: BLE001 - nunca derrubar a aplicação
            logger.exception("Erro inesperado no teste de voz.")
            self.failed.emit(f"Erro inesperado: {exc}")
