"""Separação de voz/instrumental via Demucs (dois stems: vocals / no_vocals).

Usado pela Redublagem pra manter a música de fundo e os efeitos sonoros do
vídeo original enquanto só a voz do narrador é substituída pela IA. O Demucs
baixa o modelo pré-treinado (~80 MB) na primeira execução — precisa de
internet nessa primeira vez, igual ao Whisper/Piper. Uma falha aqui nunca
derruba o pipeline: a Redublagem simplesmente segue sem música de fundo.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger("vocal_separator")

# No Windows, esconde a janela de console do subprocesso.
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_MODEL = "htdemucs"


def _pick_device(use_gpu: bool) -> str:
    if use_gpu:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
    return "cpu"


def separate_background(
    audio_path: str | Path, workdir: str | Path, use_gpu: bool = True,
) -> Path | None:
    """Roda o Demucs e retorna o caminho do stem "no_vocals" (música +
    efeitos, sem a voz). Retorna None se o Demucs não estiver disponível ou
    falhar — nesse caso o chamador deve seguir sem música de fundo.
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
            timeout=3600, creationflags=_CREATION_FLAGS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Demucs indisponível (%s); seguindo sem música de fundo.", exc)
        return None
    if result.returncode != 0:
        logger.warning(
            "Demucs falhou; seguindo sem música de fundo. %s", result.stderr[-500:],
        )
        return None

    stem = Path(audio_path).stem
    no_vocals = out_dir / _MODEL / stem / "no_vocals.wav"
    if not no_vocals.exists():
        logger.warning("Demucs não gerou 'no_vocals.wav'; seguindo sem música de fundo.")
        return None
    logger.info("Música/efeitos de fundo separados: %s", no_vocals)
    return no_vocals
