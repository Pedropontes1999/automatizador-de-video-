"""Narração por IA via Chatterbox Multilingual (Resemble AI, open-source/MIT,
https://github.com/resemble-ai/chatterbox) — roda localmente, sem custo por
caractere e sem chave de API, ao contrário da ElevenLabs (`src/audio/tts.py`).

Requer o pacote `chatterbox-tts` (`pip install chatterbox-tts`); não é uma
dependência obrigatória do app — quem não instalar continua usando só a
ElevenLabs, a síntese só falha (com aviso) se a voz "chatterbox:*" for
escolhida sem o pacote presente.
"""
from __future__ import annotations

from pathlib import Path
from threading import Lock

from src.config import constants as C
from src.utils.logger import get_logger

logger = get_logger("chatterbox_tts")

# Modelo carregado uma única vez por processo (alguns GB, baixado do Hugging
# Face na 1a execução) e reaproveitado entre chamadas: recarregar a cada
# trecho da Redublagem (um por linha de fala) inviabilizaria o tempo de
# geração.
_model = None
_model_device: str | None = None
_lock = Lock()


def _get_model(use_gpu: bool):
    global _model, _model_device
    with _lock:
        try:
            import torch
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        except ImportError as exc:
            raise RuntimeError(
                "Motor Chatterbox não instalado. Rode "
                "'pip install chatterbox-tts' para usar essa voz gratuita."
            ) from exc
        device = "cuda" if use_gpu and torch.cuda.is_available() else "cpu"
        if _model is None or _model_device != device:
            logger.info("Carregando modelo Chatterbox (%s)... pode demorar na 1a vez.", device)
            _model = ChatterboxMultilingualTTS.from_pretrained(device=device)
            _model_device = device
        return _model


def synthesize_chatterbox(
    text: str, reference_audio: str | Path | None, output_path: Path, use_gpu: bool = True,
) -> None:
    """Gera o áudio (WAV) da narração via Chatterbox, salvando em `output_path`.

    `reference_audio`: clipe de referência (poucos segundos, fala limpa) pra
    clonar uma voz; sem ele, usa a voz embutida padrão do modelo.
    """
    import torchaudio

    model = _get_model(use_gpu)
    ref = str(reference_audio) if reference_audio and Path(reference_audio).exists() else None
    wav = model.generate(text, language_id=C.CHATTERBOX_LANGUAGE, audio_prompt_path=ref)
    torchaudio.save(str(output_path), wav, model.sr)
