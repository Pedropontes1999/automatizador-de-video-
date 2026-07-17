"""Visão computacional com OpenCV: detecção de rostos/pessoas e cálculo do
centro de interesse para o reenquadramento 9:16.

Estratégia (sem custo, 100% local):
1. Amostra ~2 frames por segundo do trecho do corte.
2. Detecta rostos com o Haar Cascade frontal (embutido no OpenCV) e, como
   apoio, o detector de corpo inteiro (HOG) quando nenhum rosto aparece.
3. Suaviza a trajetória do centro com média móvel exponencial, evitando
   "tremidas" na câmera virtual.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from src.utils.logger import get_logger

logger = get_logger("face_tracker")


@dataclass(frozen=True)
class FramingResult:
    """Resultado do rastreamento para um corte.

    centers: lista de (tempo, centro_x_normalizado 0..1) já suavizada.
    face_found: False quando nenhuma pessoa foi detectada -> usar fundo desfocado.
    multi_person: True quando há 2+ rostos consistentemente no trecho.
    """

    centers: list[tuple[float, float]]
    face_found: bool
    multi_person: bool


class FaceTracker:
    """Rastreador de rostos/pessoas para auto-framing."""

    SAMPLE_FPS: float = 2.0     # frames analisados por segundo
    SMOOTHING: float = 0.25     # fator EMA (menor = mais suave)

    def __init__(self) -> None:
        cascade_dir = Path(cv2.data.haarcascades)
        self._face_cascade = cv2.CascadeClassifier(
            str(cascade_dir / "haarcascade_frontalface_default.xml")
        )
        self._eye_cascade = cv2.CascadeClassifier(
            str(cascade_dir / "haarcascade_eye.xml")
        )
        self._hog = cv2.HOGDescriptor()
        self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    # ------------------------------------------------------------------ #
    def track(self, video_path: str | Path, start: float, end: float) -> FramingResult:
        """Rastreia o trecho [start, end] e devolve a trajetória do enquadramento."""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.warning("Não foi possível abrir %s para rastreamento.", video_path)
            return FramingResult([], face_found=False, multi_person=False)

        try:
            width = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1.0
            raw: list[tuple[float, float]] = []
            multi_hits = 0
            samples = 0
            t = start
            while t < end:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ok, frame = cap.read()
                if not ok:
                    break
                samples += 1
                faces = self._detect_faces(frame)
                if len(faces) >= 2:
                    multi_hits += 1
                center_x = self._interest_center(frame, faces)
                if center_x is not None:
                    raw.append((t, center_x / width))
                t += 1.0 / self.SAMPLE_FPS
        finally:
            cap.release()

        if not raw:
            logger.info("Nenhum rosto/pessoa detectado no trecho — fundo desfocado.")
            return FramingResult([], face_found=False, multi_person=False)

        multi = samples > 0 and (multi_hits / samples) > 0.4
        return FramingResult(
            centers=self._smooth(raw), face_found=True, multi_person=multi,
        )

    # ------------------------------------------------------------------ #
    def _detect_faces(self, frame: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Detecta rostos; valida com olhos para reduzir falsos positivos."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = self._face_cascade.detectMultiScale(
            gray, scaleFactor=1.15, minNeighbors=5,
            minSize=(int(frame.shape[0] * 0.08), int(frame.shape[0] * 0.08)),
        )
        validated = []
        for (x, y, w, h) in faces:
            roi = gray[y : y + h, x : x + w]
            eyes = self._eye_cascade.detectMultiScale(roi, 1.1, 3)
            # Aceita o rosto mesmo sem olhos visíveis se for grande (perfil).
            if len(eyes) > 0 or w > frame.shape[1] * 0.15:
                validated.append((int(x), int(y), int(w), int(h)))
        return validated

    def _interest_center(
        self, frame: np.ndarray, faces: list[tuple[int, int, int, int]],
    ) -> float | None:
        """Centro X de interesse: rosto(s) > pessoa (HOG) > None."""
        if faces:
            if len(faces) == 1:
                x, _, w, _ = faces[0]
                return x + w / 2.0
            # Duas pessoas: centraliza no ponto médio ponderado pelo tamanho
            # dos rostos (auto-framing inteligente).
            total = sum(w * h for _, _, w, h in faces)
            return sum((x + w / 2.0) * (w * h) for x, _, w, h in faces) / total
        # Fallback: detector de pessoas (corpo inteiro).
        small = cv2.resize(frame, None, fx=0.5, fy=0.5)
        bodies, _ = self._hog.detectMultiScale(small, winStride=(8, 8))
        if len(bodies) > 0:
            x, _, w, _ = max(bodies, key=lambda b: b[2] * b[3])
            return (x + w / 2.0) * 2.0  # desfaz o resize 0.5
        return None

    def _smooth(self, raw: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """Média móvel exponencial sobre a trajetória do centro."""
        smoothed: list[tuple[float, float]] = []
        value = raw[0][1]
        for t, x in raw:
            value = value + self.SMOOTHING * (x - value)
            smoothed.append((t, float(np.clip(value, 0.0, 1.0))))
        return smoothed
