"""Separação de voz/instrumental via Demucs (dois stems: vocals / no_vocals).

Usado pela Redublagem tanto pra manter a música/efeitos originais quanto pra
transcrever só a voz isolada (stem "vocals"), em vez do áudio completo —
transcrever o áudio cru faz o Whisper "ouvir" fala em música/efeitos
sonoros e tratar esse texto alucinado como se fosse narração, redublando
coisa que não é o narrador. O Demucs baixa o modelo pré-treinado na primeira
execução — precisa de internet nessa primeira vez, igual ao Whisper.
Uma falha aqui nunca derruba o pipeline.

Usa o modelo "htdemucs_ft" (ensemble de 4 modelos, fine-tuned pela Meta) em
vez do "htdemucs" padrão: separa a voz de forma bem mais limpa, reduzindo o
vazamento da narração original no stem "no_vocals" (que ficava audível por
baixo da narração de IA depois da mixagem). O custo é ~4x mais lento —
aceitável porque essa etapa roda uma vez só por vídeo.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger("vocal_separator")

# No Windows, esconde a janela de console do subprocesso.
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_MODEL = "htdemucs_ft"


@dataclass
class SeparatedAudio:
    """Caminhos dos dois stems gerados pelo Demucs."""

    vocals: Path
    no_vocals: Path


def _pick_device(use_gpu: bool) -> str:
    if use_gpu:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
    return "cpu"


def separate_vocals(
    audio_path: str | Path, workdir: str | Path, use_gpu: bool = True,
) -> SeparatedAudio | None:
    """Roda o Demucs e retorna os caminhos dos stems "vocals" (só voz) e
    "no_vocals" (música + efeitos). Retorna None se o Demucs não estiver
    disponível ou falhar — nesse caso o chamador deve seguir com o áudio
    original sem separação.
    """
    device = _pick_device(use_gpu)
    out_dir = Path(workdir) / "demucs_out"
    cmd = [
        sys.executable, "-m", "demucs",
        "--two-stems", "vocals", "-n", _MODEL, "-d", device,
        "-o", str(out_dir), str(audio_path),
    ]
    logger.info("Separando voz/música com Demucs (%s)...", device)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10800, creationflags=_CREATION_FLAGS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Demucs indisponível (%s); seguindo sem separação.", exc)
        return None
    if result.returncode != 0:
        logger.warning(
            "Demucs falhou; seguindo sem separação. %s", result.stderr[-500:],
        )
        return None

    stem = Path(audio_path).stem
    stem_dir = out_dir / _MODEL / stem
    vocals = stem_dir / "vocals.wav"
    no_vocals = stem_dir / "no_vocals.wav"
    if not vocals.exists() or not no_vocals.exists():
        logger.warning("Demucs não gerou os stems esperados; seguindo sem separação.")
        return None
    logger.info("Voz e música/efeitos separados: %s / %s", vocals, no_vocals)
    return SeparatedAudio(vocals=vocals, no_vocals=no_vocals)
