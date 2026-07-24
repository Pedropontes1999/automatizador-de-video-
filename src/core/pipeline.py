"""Pipeline completo: vídeo longo -> vários Shorts prontos.

Etapas:
1. (opcional) Download do YouTube (yt-dlp)
2. Extração de áudio (FFmpeg)
3. Transcrição (Whisper, com timestamps por palavra) + JSON
4. Análise viral (Ollama) + scoring
5. Para cada corte: extração do trecho, detecção de silêncios/vícios,
   rastreamento de rosto, reframe 9:16, efeitos, legendas ASS e exportação.

O pipeline roda em thread de trabalho (nunca na GUI) e respeita o
`TaskControl` (pausa/cancelamento) entre todas as etapas.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.ai.analyzer import ViralAnalyzer, deduplicate_candidates
from src.ai.highlight_detector import detect_audio_highlights
from src.ai.ollama_client import OllamaClient
from src.ai.transcriber import WhisperTranscriber
from src.audio.enhancer import build_audio_filter_chain
from src.audio.extractor import extract_audio
from src.audio.tts import audio_duration, synthesize
from src.audio.silence import (
    detect_silences,
    find_filler_segments,
    keep_intervals,
    merge_windows,
)
from src.config.settings import Settings
from src.core.exceptions import AIAnalysisError
from src.core.task_manager import TaskControl
from src.models.domain import CutCandidate, Project, Transcription, TranscriptWord
from src.subtitle.generator import TimeRemapper, generate_ass
from src.subtitle.styles import get_style
from src.utils import ffmpeg_utils
from src.utils.logger import get_logger
from src.utils.paths import (
    new_temp_dir,
    project_output_dir,
    sanitize_filename,
    transcript_cache_path,
)
from src.video.branding import BrandingSpec, apply_branding, apply_tts_freeze_intro
from src.video.downloader import download_video, is_youtube_url
from src.video.effects import build_effects_chain
from src.video.exporter import build_filter_complex, export_short, extract_segment
from src.video.face_tracker import FaceTracker, FramingResult
from src.video.reframer import build_reframe_filter

logger = get_logger("pipeline")


def build_fixed_cuts(total_duration: float, chunk_seconds: float) -> list[CutCandidate]:
    """Divide [0, total] em cortes sequenciais de duração fixa.

    Ex.: 60 s -> Parte 01 (0:00-0:59), Parte 02 (1:00-1:59), ...
    A sobra final menor que 15 s é anexada ao último corte em vez de virar
    um clipe inútil de poucos segundos.
    """
    chunk = max(chunk_seconds, 5.0)
    cuts: list[CutCandidate] = []
    start = 0.0
    while start < total_duration:
        end = min(start + chunk, total_duration)
        if cuts and end - start < 15.0:
            cuts[-1].end = round(total_duration, 2)
            break
        cuts.append(CutCandidate(
            start=round(start, 2),
            end=round(end, 2),
            title=f"Parte {len(cuts) + 1:02d}",
            description="Corte sequencial por tempo fixo.",
            category="sequencial",
        ))
        start = end
    return cuts


@dataclass
class PipelineCallbacks:
    """Callbacks para a GUI acompanhar o processamento em tempo real."""

    on_progress: Callable[[int, str], None] = lambda pct, msg: None
    on_cut_done: Callable[[CutCandidate], None] = lambda cut: None
    on_transcription_ready: Callable[[object], None] = lambda t: None


@dataclass
class ShortsPipeline:
    """Orquestra a transformação de um vídeo longo em Shorts."""

    settings: Settings
    callbacks: PipelineCallbacks = field(default_factory=PipelineCallbacks)

    # ------------------------------------------------------------------ #
    def run(self, source: str, control: TaskControl) -> Project:
        """Executa o pipeline completo para um arquivo local ou link do YouTube."""
        cb = self.callbacks
        control.checkpoint()

        # -- Etapa 0: resolver a origem --------------------------------- #
        if is_youtube_url(source):
            cb.on_progress(2, "Baixando vídeo do YouTube...")
            video_path = download_video(
                source, progress=lambda p, m: cb.on_progress(2 + int(p * 0.06), m),
            )
        else:
            video_path = Path(source)
        info = ffmpeg_utils.video_info(video_path)
        project = Project(
            source_path=str(video_path),
            source_url=source if is_youtube_url(source) else None,
            title=video_path.stem,
            duration=info["duration"],
            status="transcribing",
        )
        temp_dir = new_temp_dir("project")
        output_dir = project_output_dir(project.title)
        control.checkpoint()

        # -- Etapas 1-2: áudio + transcrição ----------------------------- #
        # No modo anime "tempo" o vídeo é apenas dividido em blocos fixos:
        # a IA não entra e o áudio/Whisper só são necessários se as legendas
        # estiverem ativadas (pula a etapa mais lenta do pipeline).
        anime_mode = self.settings.video_category == "anime"
        fixed_mode = anime_mode and self.settings.anime_cut_mode == "tempo"
        need_transcription = not fixed_mode or self.settings.subtitles_enabled
        audio_path: Path | None = None
        transcription = Transcription(language="auto")
        if need_transcription:
            cb.on_progress(10, "Extraindo áudio...")
            audio_path = extract_audio(video_path, temp_dir)
            control.checkpoint()

            # Reutiliza a transcrição de execuções anteriores do mesmo vídeo:
            # economiza vários minutos ao reprocessar (a etapa mais lenta na CPU).
            cache_file = transcript_cache_path(video_path, self.settings.whisper_model)
            cached = WhisperTranscriber.load_cached(
                cache_file, output_dir / "transcricao.json",
            )
            if cached is None:
                cb.on_progress(15, "Transcrevendo com Whisper (pode demorar)...")
                transcriber = WhisperTranscriber(
                    self.settings.whisper_model, self.settings.use_gpu,
                )
                transcription = transcriber.transcribe(
                    audio_path, self.settings.language,
                    progress=lambda m: cb.on_progress(20, m),
                )
                # Salva em dois lugares: cache interno (estável) + pasta do
                # projeto (visível para o usuário).
                transcriber.save_json(transcription, cache_file)
                transcriber.save_json(transcription, output_dir / "transcricao.json")
            else:
                cb.on_progress(38, "Transcrição anterior encontrada — reutilizando.")
                transcription = cached
        else:
            cb.on_progress(38, "Modo tempo fixo sem legendas: pulando transcrição.")
        project.transcription = transcription
        cb.on_transcription_ready(transcription)
        control.checkpoint()

        # -- Etapa 3: análise IA (ou divisão por tempo fixo) -------------- #
        project.status = "analyzing"
        candidates: list[CutCandidate] = []
        if fixed_mode:
            chunk = self.settings.anime_fixed_seconds
            cb.on_progress(45, f"Dividindo o vídeo em cortes de {chunk} s...")
            candidates = build_fixed_cuts(info["duration"], float(chunk))
        else:
            # No modo anime os melhores momentos costumam não estar na fala
            # (lutas, cenas visuais), então a análise por transcrição vira
            # opcional e é complementada pela detecção de picos de áudio.
            if transcription.segments:
                cb.on_progress(40, "Analisando momentos virais com IA...")
                analyzer = ViralAnalyzer(
                    OllamaClient(self.settings.ollama_url),
                    self.settings.ollama_model,
                    min_duration=self.settings.min_cut_duration,
                    max_duration=self.settings.max_cut_duration,
                )
                try:
                    candidates = analyzer.analyze(
                        transcription,
                        max_cuts=self.settings.max_cuts,
                        progress=lambda m: cb.on_progress(45, m),
                    )
                except AIAnalysisError:
                    if not anime_mode:
                        raise
                    logger.warning(
                        "Análise por fala sem resultados; seguindo só com picos de áudio."
                    )
            if anime_mode:
                cb.on_progress(46, "Detectando cenas de ação pelos picos do áudio...")
                candidates += detect_audio_highlights(
                    audio_path,
                    min_duration=self.settings.min_cut_duration,
                    max_duration=self.settings.max_cut_duration,
                )
                candidates = deduplicate_candidates(candidates)
                candidates = candidates[: self.settings.max_cuts]
            candidates = [
                c for c in candidates if c.score >= self.settings.min_viral_score
            ] or candidates[:3]  # garante ao menos os 3 melhores
        if not candidates:
            raise AIAnalysisError(
                "Nenhum trecho encontrado: o vídeo não tem fala relevante "
                "nem picos de áudio destacados."
            )
        project.cuts = candidates
        self._save_cuts_json(candidates, output_dir)
        control.checkpoint()

        # -- Etapa 3.5: narração por IA (uma vez, reusada em cada corte) -- #
        tts_path: Path | None = None
        tts_seconds = 0.0
        if self.settings.tts_enabled and self.settings.tts_text.strip():
            cb.on_progress(48, "Gerando narração com IA...")
            tts_path = synthesize(
                self.settings.tts_text, self.settings.tts_voice,
                temp_dir / "narracao.mp3",
                api_key=self.settings.elevenlabs_api_key,
            )
            if tts_path is not None:
                tts_seconds = audio_duration(tts_path)

        # -- Etapa 3.6: duração da música de fundo (uma vez, evita reabrir o
        # arquivo a cada corte) — usada para variar o ponto de início da
        # música em cada corte em vez de sempre tocar do início dela.
        music_duration = 0.0
        if self.settings.music_path and Path(self.settings.music_path).exists():
            try:
                music_duration = audio_duration(Path(self.settings.music_path))
            except Exception as exc:  # noqa: BLE001 - música é só estilo, não derruba o job
                logger.warning("Não foi possível medir a música de fundo (%s).", exc)

        # -- Etapa 4: edição e exportação de cada corte ------------------ #
        project.status = "cutting"
        tracker = FaceTracker()
        total = len(candidates)
        for rank, cut in enumerate(candidates, start=1):
            control.checkpoint()
            base_pct = 50 + int(48 * (rank - 1) / total)
            cb.on_progress(base_pct, f"Gerando corte {rank}/{total}: {cut.title}")
            try:
                self._export_cut(
                    cut, rank, video_path, info, transcription,
                    tracker, temp_dir, output_dir,
                    tts_path=tts_path, tts_seconds=tts_seconds,
                    music_duration=music_duration,
                )
                cut.status = "done"
            except Exception as exc:  # noqa: BLE001 - um corte não derruba o job
                cut.status = "error"
                logger.error("Falha no corte %d (%s): %s", rank, cut.title, exc)
            cb.on_cut_done(cut)

        project.status = "done"
        cb.on_progress(100, f"Concluído! {total} cortes em {output_dir}")
        return project

    # ------------------------------------------------------------------ #
    def _export_cut(
        self,
        cut: CutCandidate,
        rank: int,
        video_path: Path,
        info: dict,
        transcription,
        tracker: FaceTracker,
        temp_dir: Path,
        output_dir: Path,
        tts_path: Path | None = None,
        tts_seconds: float = 0.0,
        music_duration: float = 0.0,
    ) -> None:
        """Edita e exporta um único corte (roda dentro do loop do pipeline)."""
        s = self.settings
        cut.status = "processing"

        # 1) Extrai o trecho bruto (preciso ao frame).
        segment = extract_segment(
            video_path, cut.start, cut.end, temp_dir / f"cut_{rank:02d}.mp4",
        )

        # 2) Detecta o que remover: silêncios (no trecho) + vícios (transcrição).
        # No modo anime a limpeza fica desativada: silêncio dramático e
        # pausas de ação fazem parte da cena — cortá-los mutila o clipe.
        anime_mode = s.video_category == "anime"
        keep: list[tuple[float, float]] | None = None
        remapper: TimeRemapper | None = None
        if not anime_mode and (s.remove_silences or s.remove_fillers):
            remove: list[tuple[float, float]] = []
            if s.remove_silences:
                remove += detect_silences(segment)
            if s.remove_fillers:
                remove += [
                    (ws - cut.start, we - cut.start)
                    for ws, we in find_filler_segments(
                        [seg for seg in transcription.segments
                         if seg.end > cut.start and seg.start < cut.end]
                    )
                ]
            remove = merge_windows(remove)
            if remove:
                keep = keep_intervals(remove, 0.0, cut.duration)
                remapper = TimeRemapper(keep)

        # 3) Define o modo de saída:
        #    - "vertical": rastreia o rosto e reenquadra em 9:16;
        #    - "original": mantém o formato do vídeo (sem rastreamento,
        #      muito mais rápido).
        if s.output_format == "original":
            out_w, out_h = info["width"], info["height"]
            # Apenas garante dimensões pares (exigência do H264).
            reframe = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        else:
            out_w, out_h = s.resolution_width, s.resolution_height
            if anime_mode:
                # Rosto de anime não é detectável pelo Haar Cascade (treinado
                # em rostos reais), então não há rastreamento. Enquadramento
                # conforme a preferência: "blur" mostra o vídeo inteiro sobre
                # ele mesmo desfocado (estilo canais de corte); "crop" faz
                # crop central estático preenchendo a tela.
                if s.anime_framing == "crop":
                    framing = FramingResult(
                        centers=[(cut.start, 0.5)], face_found=True, multi_person=False,
                    )
                else:
                    framing = FramingResult([], face_found=False, multi_person=False)
            else:
                framing = tracker.track(video_path, cut.start, cut.end)
            framing = self._remap_framing(framing, cut.start, remapper)
            reframe = build_reframe_filter(
                info["width"], info["height"], out_w, out_h, framing, cut_start=0.0,
            )

        # 4) Monta filtros: efeitos + legenda + áudio.
        edited_duration = (
            sum(e - b for b, e in keep) if keep else cut.duration
        )
        effect_filters = build_effects_chain(
            s.effects, out_w, out_h, s.fps, edited_duration,
        )
        subtitle_path: Path | None = None
        cut_words = self._words_in_range(transcription, cut.start, cut.end)
        # Sem palavras no trecho (ex.: cena de ação sem fala) não há legenda.
        if s.subtitles_enabled and cut_words:
            subtitle_path = generate_ass(
                cut_words,
                get_style(s.subtitle_style),
                temp_dir / f"cut_{rank:02d}.ass",
                cut_start=cut.start,
                remapper=remapper,
                width=out_w,
                height=out_h,
            )
        audio_chain = build_audio_filter_chain(
            s.audio_normalize, s.audio_denoise, s.audio_compress,
        )
        graph = build_filter_complex(
            reframe, effect_filters, subtitle_path, keep, audio_chain,
        )

        # 4.5) Estilo/identidade visual (página Estilo): marca d'água, textos,
        # barra de progresso e música de fundo.
        part_text = (
            cut.title if cut.category == "sequencial" and s.show_part_number else ""
        )
        graph = apply_branding(graph, BrandingSpec(
            settings=s,
            out_width=out_w,
            out_height=out_h,
            duration=edited_duration,
            workdir=temp_dir,
            tag=f"cut_{rank:02d}",
            part_text=part_text,
            source_start=cut.start,
            source_duration=info["duration"],
            music_duration=music_duration,
        ))
        # 4.6) Narração por IA: congela o primeiro frame durante a fala em vez
        # de tocar por cima do vídeo já em andamento (evita dessincronia).
        graph = apply_tts_freeze_intro(graph, tts_path, tts_seconds)

        # 5) Exporta o MP4 final. Cortes sequenciais não têm nota viral,
        # então saem com nome limpo ("01_Parte_01.mp4").
        if cut.category == "sequencial":
            filename = f"{rank:02d}_{sanitize_filename(cut.title)}.mp4"
        else:
            filename = f"{rank:02d}_[{cut.score}]_{sanitize_filename(cut.title)}.mp4"
        output = export_short(
            segment, output_dir / filename, graph,
            fps=s.fps, crf=s.quality_crf, use_gpu=s.use_gpu,
        )
        cut.output_path = str(output)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _words_in_range(transcription, start: float, end: float) -> list[TranscriptWord]:
        """Todas as palavras da transcrição dentro do intervalo do corte."""
        words: list[TranscriptWord] = []
        for seg in transcription.segments:
            if seg.end < start or seg.start > end:
                continue
            words.extend(w for w in seg.words if w.start >= start and w.end <= end)
        return words

    @staticmethod
    def _remap_framing(
        framing: FramingResult, cut_start: float, remapper: TimeRemapper | None,
    ) -> FramingResult:
        """Converte os tempos do rastreamento para a linha do tempo editada."""
        if not framing.centers:
            return framing
        centers: list[tuple[float, float]] = []
        for t, x in framing.centers:
            local = t - cut_start
            mapped = remapper.remap(local) if remapper else local
            if mapped is not None:
                centers.append((mapped, x))
        return FramingResult(
            centers=centers,
            face_found=framing.face_found and bool(centers),
            multi_person=framing.multi_person,
        )

    @staticmethod
    def _save_cuts_json(cuts: list[CutCandidate], output_dir: Path) -> None:
        """Salva o resultado da análise IA em cortes.json."""
        (output_dir / "cortes.json").write_text(
            json.dumps([c.to_dict() for c in cuts], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
