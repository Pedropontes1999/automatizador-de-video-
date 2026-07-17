"""Cliente HTTP para o Ollama (LLM local em http://localhost:11434).

Sem dependências pagas: usa apenas `requests` contra a API local do Ollama.
"""
from __future__ import annotations

import json
import re

import requests

from src.core.exceptions import AIAnalysisError
from src.utils.logger import get_logger

logger = get_logger("ollama")


class OllamaClient:
    """Comunicação com o servidor Ollama local."""

    def __init__(self, base_url: str = "http://localhost:11434", timeout: int = 1800) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        """Verifica se o servidor Ollama está rodando."""
        try:
            return requests.get(f"{self.base_url}/api/tags", timeout=3).ok
        except requests.RequestException:
            return False

    def list_models(self) -> list[str]:
        """Lista os modelos instalados localmente no Ollama."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
        except requests.RequestException as exc:
            logger.warning("Não foi possível listar modelos do Ollama: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    def generate(self, model: str, prompt: str, system: str | None = None) -> str:
        """Gera uma resposta completa (não-streaming) do modelo."""
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_ctx": 8192},
        }
        if system:
            payload["system"] = system
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate", json=payload, timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except requests.ConnectionError as exc:
            raise AIAnalysisError(
                "Ollama não está rodando. Inicie com 'ollama serve' e baixe um "
                f"modelo com 'ollama pull {model}'."
            ) from exc
        except requests.RequestException as exc:
            raise AIAnalysisError(f"Erro na chamada ao Ollama: {exc}") from exc

    # ------------------------------------------------------------------ #
    def generate_json(self, model: str, prompt: str, system: str | None = None) -> list | dict:
        """Gera resposta e extrai o JSON dela (LLMs às vezes adicionam texto extra)."""
        raw = self.generate(model, prompt, system)
        return self._extract_json(raw)

    @staticmethod
    def _extract_json(text: str) -> list | dict:
        """Extrai o primeiro bloco JSON válido de uma resposta de LLM."""
        # Remove cercas de código markdown (```json ... ```).
        text = re.sub(r"```(?:json)?", "", text).strip()
        # Tenta o texto inteiro primeiro; depois procura o maior [] ou {}.
        candidates = [text]
        for opener, closer in (("[", "]"), ("{", "}")):
            start, end = text.find(opener), text.rfind(closer)
            if start != -1 and end > start:
                candidates.append(text[start : end + 1])
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        raise AIAnalysisError(
            f"A IA não retornou JSON válido. Resposta parcial: {text[:300]}"
        )
