"""Análise da transcrição com LLM local (Ollama) para encontrar momentos virais.

A transcrição inteira é enviada em janelas (chunks) que respeitam o contexto do
modelo. Para cada janela a IA devolve candidatos a corte com tempos, título,
descrição, hashtags, categoria e notas por critério.
"""
from __future__ import annotations

from typing import Callable

from src.ai.ollama_client import OllamaClient
from src.ai.scoring import compute_final_score
from src.core.exceptions import AIAnalysisError
from src.models.domain import CutCandidate, Transcription, TranscriptSegment
from src.utils.logger import get_logger

logger = get_logger("analyzer")

ProgressFn = Callable[[str], None]

_SYSTEM_PROMPT = """Você é um especialista em conteúdo viral para TikTok, \
YouTube Shorts e Reels. Sua tarefa é analisar transcrições de vídeos longos e \
encontrar os melhores trechos para virar Shorts.

Procure por: ganchos fortes, momentos emocionantes, curiosidades, polêmicas, \
suspense, dinheiro, negócios, histórias, momentos engraçados, perguntas com \
respostas fortes e frases de impacto.

Responda SEMPRE e SOMENTE com JSON válido, sem texto adicional."""

_ANALYSIS_PROMPT = """Transcrição em frases numeradas (cada linha: [número] frase):

{transcript}

Encontre até {max_candidates} trechos com potencial viral nesta parte.
Regras:
- Um trecho é um intervalo de frases consecutivas: "start_index" (número da
  primeira frase) e "end_index" (número da última frase), ambos entre
  {first_index} e {last_index}.
- Escolha intervalos que durem aproximadamente entre {min_dur} e {max_dur}
  segundos de fala (entre {min_lines} e {max_lines} frases, em média).
- O trecho deve fazer sentido sozinho, com gancho logo na primeira frase.

Responda com uma lista JSON. Cada item:
{{
  "start_index": <número da primeira frase>,
  "end_index": <número da última frase>,
  "title": "<título chamativo em até 60 caracteres>",
  "description": "<descrição curta para redes sociais>",
  "hashtags": ["#tag1", "#tag2", "#tag3"],
  "category": "<gancho|emocao|curiosidade|polemica|suspense|dinheiro|negocios|historia|humor|pergunta|impacto>",
  "reason": "<por que este trecho é viral>",
  "scores": {{
    "retencao": <0-100>,
    "viral": <0-100>,
    "engajamento": <0-100>,
    "curiosidade": <0-100>,
    "gancho": <0-100>,
    "originalidade": <0-100>
  }}
}}"""


class ViralAnalyzer:
    """Encontra e pontua momentos virais na transcrição usando o Ollama."""

    # Segundos de transcrição enviados por janela ao LLM (~6 min).
    # Janelas curtas mantêm o prompt pequeno — essencial para CPU.
    CHUNK_SECONDS: float = 360.0

    def __init__(
        self,
        client: OllamaClient,
        model: str,
        min_duration: float = 20.0,
        max_duration: float = 90.0,
    ) -> None:
        self.client = client
        self.model = model
        self.min_duration = min_duration
        self.max_duration = max_duration

    # ------------------------------------------------------------------ #
    def analyze(
        self,
        transcription: Transcription,
        max_cuts: int = 10,
        progress: ProgressFn | None = None,
    ) -> list[CutCandidate]:
        """Analisa TODA a transcrição e retorna candidatos ordenados por nota."""
        chunks = self._split_chunks(transcription.segments)
        candidates: list[CutCandidate] = []

        for i, chunk in enumerate(chunks, start=1):
            if progress:
                progress(f"IA analisando parte {i}/{len(chunks)}...")
            try:
                candidates.extend(self._analyze_chunk(chunk))
            except AIAnalysisError as exc:
                # Uma janela com falha não derruba a análise inteira.
                logger.warning("Falha na parte %d/%d: %s", i, len(chunks), exc)

        if not candidates:
            raise AIAnalysisError(
                "A IA não encontrou nenhum trecho válido. Tente outro modelo "
                "ou verifique se o vídeo possui fala."
            )

        candidates = deduplicate_candidates(candidates)
        candidates.sort(key=lambda c: c.score, reverse=True)
        logger.info("Análise concluída: %d candidatos únicos.", len(candidates))
        return candidates[:max_cuts]

    # ------------------------------------------------------------------ #
    def _analyze_chunk(self, segments: list[TranscriptSegment]) -> list[CutCandidate]:
        """Roda o LLM em uma janela de segmentos e valida a resposta.

        Usa frases NUMERADAS em vez de timestamps: modelos pequenos erram
        muito ao copiar tempos em segundos, mas acertam índices inteiros.
        Os tempos reais vêm da transcrição, com precisão total.
        """
        transcript_text = "\n".join(
            f"[{s.index}] {s.text.strip()}" for s in segments
        )
        avg_seg = max(
            sum(s.duration for s in segments) / len(segments), 1.0,
        )
        prompt = _ANALYSIS_PROMPT.format(
            transcript=transcript_text,
            max_candidates=5,
            min_dur=int(self.min_duration),
            max_dur=int(self.max_duration),
            first_index=segments[0].index,
            last_index=segments[-1].index,
            min_lines=max(int(self.min_duration / avg_seg), 2),
            max_lines=max(int(self.max_duration / avg_seg), 4),
        )
        data = self.client.generate_json(self.model, prompt, system=_SYSTEM_PROMPT)
        if isinstance(data, dict):  # alguns modelos devolvem {"cuts": [...]}
            data = next((v for v in data.values() if isinstance(v, list)), [])

        by_index = {s.index: s for s in segments}
        results: list[CutCandidate] = []
        for item in data:
            candidate = self._validate_item(item, by_index)
            if candidate is not None:
                results.append(candidate)
        logger.info(
            "Janela analisada: IA retornou %d itens, %d válidos.",
            len(data) if isinstance(data, list) else 0, len(results),
        )
        return results

    def _validate_item(
        self, item: dict, by_index: dict[int, TranscriptSegment],
    ) -> CutCandidate | None:
        """Converte um item JSON da IA em CutCandidate, descartando inválidos."""
        try:
            start_idx = int(item["start_index"])
            end_idx = int(item["end_index"])
        except (KeyError, TypeError, ValueError):
            return None
        if start_idx not in by_index or end_idx not in by_index or end_idx < start_idx:
            return None

        # Ajuste automático de duração: encolhe trechos longos demais
        # (removendo frases do fim) em vez de descartá-los.
        start = by_index[start_idx].start
        end = by_index[end_idx].end
        while end - start > self.max_duration and end_idx > start_idx:
            end_idx -= 1
            end = by_index[end_idx].end
        duration = end - start
        if duration < self.min_duration * 0.6:
            return None

        raw_scores = item.get("scores", {}) or {}
        breakdown = {
            k: max(0, min(100, int(raw_scores.get(k, 50) or 50)))
            for k in ("retencao", "viral", "engajamento", "curiosidade", "gancho", "originalidade")
        }
        final = compute_final_score(breakdown, duration, self.min_duration, self.max_duration)
        return CutCandidate(
            start=max(0.0, start),
            end=end,
            title=str(item.get("title", "Short sem título"))[:80],
            description=str(item.get("description", "")),
            hashtags=[str(h) for h in item.get("hashtags", [])][:8],
            category=str(item.get("category", "geral")),
            reason=str(item.get("reason", "")),
            score=final,
            score_breakdown=breakdown,
        )

    # ------------------------------------------------------------------ #
    def _split_chunks(
        self, segments: list[TranscriptSegment],
    ) -> list[list[TranscriptSegment]]:
        """Divide os segmentos em janelas de até CHUNK_SECONDS."""
        chunks: list[list[TranscriptSegment]] = []
        current: list[TranscriptSegment] = []
        window_start = 0.0
        for seg in segments:
            if current and seg.end - window_start > self.CHUNK_SECONDS:
                chunks.append(current)
                current = []
                window_start = seg.start
            current.append(seg)
        if current:
            chunks.append(current)
        return chunks


def deduplicate_candidates(candidates: list[CutCandidate]) -> list[CutCandidate]:
    """Remove candidatos com forte sobreposição, mantendo o de maior nota."""
    kept: list[CutCandidate] = []
    for cand in sorted(candidates, key=lambda c: c.score, reverse=True):
        overlaps = any(
            min(cand.end, k.end) - max(cand.start, k.start) > 0.5 * cand.duration
            for k in kept
        )
        if not overlaps:
            kept.append(cand)
    return kept
