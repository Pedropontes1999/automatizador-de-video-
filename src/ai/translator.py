"""Tradução dos trechos transcritos da Redublagem para PT-BR via Ollama.

Usada quando o vídeo de origem está em outro idioma: o Whisper transcreve
no idioma original, mas a única voz de narração disponível (ElevenLabs,
ver `src/audio/tts.py`) é em português — mandar sintetizar texto em outro
idioma com ela sai com pronúncia/sotaque errado. Este módulo traduz
os trechos revisados antes da síntese, preservando a quantidade de linhas:
cada linha é um trecho sincronizado com o tempo original do vídeo, então
perder/fundir uma quebra a sincronização.
"""
from __future__ import annotations

from typing import Callable

from src.ai.ollama_client import OllamaClient
from src.core.exceptions import AIAnalysisError
from src.utils.logger import get_logger

logger = get_logger("translator")

# Trechos por chamada ao Ollama. Lotes grandes demais estouram o contexto
# do modelo e fazem a resposta JSON vir truncada/incompleta.
_BATCH_SIZE = 25

_SYSTEM_PROMPT = (
    "Você é um tradutor profissional. Traduza cada trecho numerado para "
    "português do Brasil (PT-BR), em tom natural e coloquial, adequado "
    "para narração falada. Responda APENAS com um array JSON de strings, "
    "na mesma ordem e quantidade dos trechos recebidos — um item por "
    "trecho, sem numeração dentro do texto, sem comentários, sem markdown."
)

# Fallback pra quando o pedido de JSON falha até linha a linha: modelos
# pequenos (ex.: qwen2.5:3b) costumam ignorar "responda em JSON" quando é
# só 1 item e devolvem o texto puro. Em vez de desistir e manter a linha
# sem traduzir, pede a tradução em texto simples (sem exigir JSON) — sempre
# mais tolerante de parsear do que um array de 1 elemento.
_SINGLE_SYSTEM_PROMPT = (
    "Você é um tradutor profissional. Traduza o texto do usuário para "
    "português do Brasil (PT-BR), em tom natural e coloquial, adequado "
    "para narração falada. Responda APENAS com a tradução, sem aspas, "
    "sem comentários, sem explicações."
)


def _translate_single_plain(client: OllamaClient, model: str, text: str) -> str:
    """Traduz um único trecho pedindo texto puro (não JSON) — usado como
    último recurso quando a tradução em JSON falha mesmo isolada."""
    raw = client.generate(model, text, system=_SINGLE_SYSTEM_PROMPT)
    translated = raw.strip()
    if translated.startswith(("[", "{")):
        # A IA ignorou a instrução e mandou JSON mesmo assim; tenta extrair
        # a string de dentro em vez de devolver o JSON cru como tradução.
        try:
            parsed = OllamaClient._extract_json(raw)
            if isinstance(parsed, list) and parsed:
                return str(parsed[0]).strip()
            if isinstance(parsed, str):
                return parsed.strip()
        except AIAnalysisError:
            pass
    return translated.strip("\"'")


def _translate_batch(client: OllamaClient, model: str, batch: list[str]) -> list[str]:
    numbered = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(batch))
    prompt = (
        f"Traduza estes {len(batch)} trecho(s) para português do Brasil. "
        f"Devolva um array JSON com exatamente {len(batch)} string(s), "
        f"uma tradução por trecho:\n\n{numbered}"
    )
    result = client.generate_json(model, prompt, system=_SYSTEM_PROMPT)
    if not isinstance(result, list) or len(result) != len(batch):
        got = len(result) if isinstance(result, list) else type(result).__name__
        raise AIAnalysisError(f"Tradução veio com {got} item(ns), esperado {len(batch)}.")
    return [str(item).strip() for item in result]


def translate_segments(
    texts: list[str], model: str, ollama_url: str,
    progress: Callable[[int, str], None] | None = None,
) -> list[str]:
    """Traduz `texts` para PT-BR, preservando a quantidade de linhas.

    Linhas vazias são mantidas vazias (não são trechos falados). Traduz em
    lotes pra não estourar o contexto do modelo; se um lote vier com uma
    quantidade errada de itens, refaz linha a linha (mais lento, mas nunca
    perde/funde uma linha — a sincronização por trecho depende disso). Se
    até a tradução isolada falhar, mantém o texto original naquela linha
    em vez de travar a Redublagem inteira.
    """
    client = OllamaClient(base_url=ollama_url)
    if not client.is_available():
        raise AIAnalysisError(
            "Ollama não está rodando. Inicie com 'ollama serve' antes de traduzir."
        )

    indices = [i for i, t in enumerate(texts) if t.strip()]
    results = list(texts)
    if not indices:
        return results

    total_batches = (len(indices) + _BATCH_SIZE - 1) // _BATCH_SIZE
    for batch_num, start in enumerate(range(0, len(indices), _BATCH_SIZE)):
        batch_indices = indices[start : start + _BATCH_SIZE]
        batch_texts = [texts[i] for i in batch_indices]
        if progress:
            progress(
                int(batch_num / total_batches * 100),
                f"Traduzindo trechos {start + 1}-{start + len(batch_indices)} de {len(indices)}...",
            )
        try:
            translated = _translate_batch(client, model, batch_texts)
        except AIAnalysisError as exc:
            logger.warning("Lote de tradução falhou (%s); tentando linha a linha.", exc)
            translated = []
            for text in batch_texts:
                try:
                    single = _translate_single_plain(client, model, text)
                    translated.append(single if single else text)
                except AIAnalysisError:
                    logger.warning("Falha ao traduzir um trecho isolado; mantendo o original.")
                    translated.append(text)
        for idx, translated_text in zip(batch_indices, translated):
            results[idx] = translated_text

    if progress:
        progress(100, "Tradução concluída.")
    return results
