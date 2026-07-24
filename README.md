# ⚡ AUTO SHORTS AI

Transforme vídeos longos em **vários Shorts** automaticamente com IA — **100% local e gratuito**.
Sem APIs pagas: Whisper transcreve, Ollama analisa, OpenCV enquadra e o FFmpeg exporta.

## O que ele faz

1. Você adiciona um vídeo (arquivo, arrastar-e-soltar ou link do YouTube autorizado por você).
2. Clica em **ANALISAR**.
3. O programa:
   - Extrai o áudio e transcreve com **Whisper** (timestamps por palavra);
   - Analisa **toda** a transcrição com um LLM local via **Ollama** (Qwen, Llama, Mistral, Gemma...);
   - Encontra ganchos, momentos emocionantes, curiosidades, polêmicas, humor, histórias e frases de impacto;
   - Dá nota **0-100** a cada trecho (retenção, viralidade, engajamento, gancho, originalidade, duração);
   - Extrai os melhores cortes, remove silêncios/pausas/vícios de fala;
   - Reenquadra em **9:16** centralizando o rosto (OpenCV) — ou aplica fundo desfocado;
   - Gera legendas estilo **TikTok** com palavra ativa colorida e animada (7 temas);
   - Aplica efeitos (zoom automático, jump zoom, fade, glow) e trata o áudio (loudnorm, denoise, compressor, limiter);
   - Exporta em **MP4 / H264 / AAC / 1080x1920**, usando GPU (NVENC) quando disponível.

## Requisitos

| Ferramenta | Como instalar |
|---|---|
| Python 3.12 | https://python.org |
| FFmpeg (com ffprobe) | https://ffmpeg.org — adicione ao PATH |
| Ollama | https://ollama.com — depois `ollama pull qwen2.5:7b` |
| GPU NVIDIA (opcional) | acelera Whisper e a exportação |

## Instalação

```bash
cd AUTO-SHORTS-AI
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

> **PyTorch com CUDA (opcional, recomendado com GPU NVIDIA):**
> `pip install torch --index-url https://download.pytorch.org/whl/cu121`

## Uso

```bash
ollama serve                  # deixe o Ollama rodando
python main.py
```

Atalho: `Ctrl+S` salva a página aberta (Redublagem).

Os Shorts finais ficam em `output/<nome do vídeo>/`, junto com `transcricao.json` e `cortes.json`.

## Estrutura do projeto (Clean Architecture)

```
AUTO-SHORTS-AI/
├── main.py                  # ponto de entrada
├── config.json              # configurações do usuário
├── requirements.txt
├── src/
│   ├── config/              # constantes + settings persistidos
│   ├── models/              # dataclasses de domínio (puras)
│   ├── core/                # pipeline, fila de tarefas, exceções
│   ├── ai/                  # Whisper, cliente Ollama, análise viral, scoring
│   ├── audio/               # extração, filtros (loudnorm/denoise), silêncios
│   ├── video/               # yt-dlp, face tracking, reframe 9:16, efeitos, export
│   ├── subtitle/            # estilos + gerador ASS com karaokê por palavra
│   ├── database/            # SQLite (schema + repositórios)
│   ├── services/            # casos de uso (pipeline + banco + plugins)
│   ├── workers/             # QThread — IA nunca roda na thread da GUI
│   ├── gui/                 # PySide6: tema Discord-like, páginas, widgets
│   ├── plugins/             # sistema de plugins (plugin_*.py auto-carregados)
│   └── utils/               # logger, FFmpeg, caminhos, monitor de sistema
├── logs/  temp/  output/  downloads/  assets/
```

## Interface

- Tema escuro estilo Discord;
- Sidebar: **Editar Shorts · Download · Redublagem**;
- Barra de progresso + logs em tempo real;
- Cards de cada corte com título, nota viral, hashtags e botão para abrir o MP4;
- Dashboard com uso de CPU/GPU/RAM, contagem de cortes e tempo economizado;
- Fila de processamento com **pausar / retomar / cancelar**.

## Plugins

Crie `src/plugins/plugin_meunome.py` com uma classe herdando de `PluginBase`
(veja `plugin_exemplo.py`). Hooks: `on_app_start`, `on_project_start`,
`on_project_done`, `on_cut_exported`.

## Aviso legal

Baixe apenas vídeos **seus ou com autorização do detentor dos direitos**.
O uso do yt-dlp é de responsabilidade do usuário.
