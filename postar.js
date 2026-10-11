const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const BASE = __dirname;
const CONTA = process.argv[2] || process.env.CONTA || 'conta1';
const CONTA_DIR = path.join(BASE, 'contas', CONTA);

if (!fs.existsSync(CONTA_DIR)) {
  console.error(`Conta "${CONTA}" nao encontrada em contas/${CONTA}. Contas disponiveis: ${fs.readdirSync(path.join(BASE, 'contas')).join(', ')}`);
  process.exit(1);
}

const cfg = JSON.parse(fs.readFileSync(path.join(CONTA_DIR, 'config.json'), 'utf8'));
const estado = JSON.parse(fs.readFileSync(path.join(CONTA_DIR, 'estado.json'), 'utf8'));
const legendas = JSON.parse(fs.readFileSync(path.join(CONTA_DIR, 'legendas.json'), 'utf8'));
const videoUrls = JSON.parse(fs.readFileSync(path.join(CONTA_DIR, 'video_urls.json'), 'utf8'));
const pageToken = process.env.PAGE_TOKEN || fs.readFileSync(path.join(BASE, 'segredos', `${CONTA}_page_token.txt`), 'utf8').trim();
const capaFile = path.join(CONTA_DIR, 'capa_url.txt');
const capaUrl = fs.existsSync(capaFile) ? fs.readFileSync(capaFile, 'utf8').trim() : '';

const GRAPH = 'https://graph.facebook.com/v21.0';

// Avisos (issues) no idioma escolhido no painel: config.json "idioma" = "pt" | "en".
const TXT = {
  pt: {
    acabou: ['Acabaram os vídeos', 'Todos os vídeos da fila já foram postados. Envie mais vídeos pelo painel.'],
    falha: ['Falha ao postar', (n, m) => `video_${n} falhou: ${m}`],
    bio: [l => `Trocar a bio do Instagram (lote ${l})`, (l, leg) => `Nova legenda do lote ${l}:\n\n${leg}`],
    acabando: ['Vídeos acabando', 'Faltam 12 vídeos pra postar. Envie mais vídeos pelo painel.'],
    erro: 'Erro na automação',
  },
  en: {
    acabou: ['Out of videos', 'All videos in the queue have been posted. Upload more videos in the panel.'],
    falha: ['Post failed', (n, m) => `video_${n} failed: ${m}`],
    bio: [l => `Update your Instagram bio (batch ${l})`, (l, leg) => `New caption for batch ${l}:\n\n${leg}`],
    acabando: ['Running out of videos', '12 videos left to post. Upload more videos in the panel.'],
    erro: 'Automation error',
  },
};
const T = TXT[cfg.idioma] || TXT.pt;
const LOG_FILE = path.join(BASE, 'postar.log');
const NA_NUVEM = process.env.GITHUB_ACTIONS === 'true';

function log(msg) {
  const line = `[${new Date().toISOString()}] [${CONTA}] ${msg}`;
  console.log(line);
  try { fs.appendFileSync(LOG_FILE, line + '\n'); } catch (e) { /* sistema de arquivos read-only em alguns runners */ }
}

async function avisarViaIssue(titulo, mensagem) {
  const repo = process.env.GITHUB_REPOSITORY;
  const token = process.env.GITHUB_TOKEN;
  if (!repo || !token) { log('Sem GITHUB_REPOSITORY/GITHUB_TOKEN para abrir issue.'); return; }
  const headers = { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json' };
  const title = `[${CONTA}] ${titulo}`;
  // Fila vazia roda a cada horário: sem isso viraria um e-mail a cada 30 min.
  const abertas = await fetch(`https://api.github.com/repos/${repo}/issues?state=open&per_page=100`, { headers });
  if (abertas.ok && (await abertas.json()).some(i => i.title === title)) { log(`Aviso "${title}" já está aberto.`); return; }
  const res = await fetch(`https://api.github.com/repos/${repo}/issues`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ title, body: mensagem }),
  });
  if (!res.ok) log(`Falha ao criar issue: ${res.status} ${await res.text()}`);
}

function avisar(titulo, mensagem) {
  if (NA_NUVEM) {
    avisarViaIssue(titulo, mensagem).catch(e => log(`Falha ao avisar via issue: ${e.message}`));
    return;
  }
  try {
    const script = `Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('${mensagem.replace(/'/g, "''")}', '${`[${CONTA}] ${titulo}`.replace(/'/g, "''")}')`;
    execSync(`powershell -NoProfile -Command "${script}"`, { stdio: 'ignore' });
  } catch (e) {
    log(`Falha ao mostrar aviso: ${e.message}`);
  }
  try { fs.writeFileSync(path.join(BASE, `AVISO_${CONTA}_${Date.now()}.txt`), `${titulo}\n\n${mensagem}`); } catch (e) { /* ignore */ }
}

async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function criarContainer(videoUrl, legenda) {
  const params = new URLSearchParams({
    media_type: 'REELS',
    video_url: videoUrl,
    caption: legenda,
    access_token: pageToken,
  });
  if (capaUrl) params.set('cover_url', capaUrl);
  const res = await fetch(`${GRAPH}/${cfg.ig_user_id}/media?${params.toString()}`, { method: 'POST' });
  const data = await res.json();
  if (data.error) throw new Error(JSON.stringify(data.error));
  return data.id;
}

async function esperarProcessamento(containerId) {
  for (let i = 0; i < 30; i++) {
    const res = await fetch(`${GRAPH}/${containerId}?fields=status_code&access_token=${pageToken}`);
    const data = await res.json();
    if (data.error) throw new Error(JSON.stringify(data.error));
    if (data.status_code === 'FINISHED') return true;
    if (data.status_code === 'ERROR') throw new Error('Processamento falhou no lado da Meta');
    await sleep(10000);
  }
  throw new Error('Tempo de processamento excedido');
}

async function publicar(containerId) {
  const params = new URLSearchParams({ creation_id: containerId, access_token: pageToken });
  const res = await fetch(`${GRAPH}/${cfg.ig_user_id}/media_publish?${params.toString()}`, { method: 'POST' });
  const data = await res.json();
  if (data.error) throw new Error(JSON.stringify(data.error));
  return data.id;
}

function salvarEstado() {
  fs.writeFileSync(path.join(CONTA_DIR, 'estado.json'), JSON.stringify(estado, null, 2));
}

async function main() {
  if (estado.proximo_video > estado.video_maximo) {
    log('Nenhum vídeo restante para postar.');
    avisar(T.acabou[0], T.acabou[1]);
    return;
  }

  const num = estado.proximo_video;
  const videoUrl = videoUrls[String(num)];
  if (!videoUrl) {
    log(`video_${num} não tem URL no Cloudinary ainda. Abortando.`);
    return;
  }

  const legendaObj = legendas.length ? legendas[(estado.lote_atual - 1) % legendas.length] : { legenda: '' };
  log(`Postando video_${num} (lote ${estado.lote_atual}, post ${estado.posts_no_lote_atual + 1}/${estado.tamanho_lote})`);

  try {
    const containerId = await criarContainer(videoUrl, legendaObj.legenda);
    await esperarProcessamento(containerId);
    const mediaId = await publicar(containerId);
    log(`OK - video_${num} publicado. media_id=${mediaId}`);
  } catch (e) {
    log(`FALHOU video_${num}: ${e.message}`);
    avisar(T.falha[0], T.falha[1](num, e.message));
    return;
  }

  estado.proximo_video += 1;
  estado.posts_no_lote_atual += 1;

  if (estado.posts_no_lote_atual >= estado.tamanho_lote) {
    estado.posts_no_lote_atual = 0;
    estado.lote_atual += 1;
    if (legendas.length > 1) {
      const novaLegendaObj = legendas[(estado.lote_atual - 1) % legendas.length];
      log(`Legenda trocou para o lote ${estado.lote_atual}. Atualize a bio.`);
      avisar(T.bio[0](estado.lote_atual), T.bio[1](estado.lote_atual, novaLegendaObj.legenda));
    }
  }

  const restantes = estado.video_maximo - estado.proximo_video + 1;
  if (restantes === 12) {
    log('Faltam 12 vídeos. Avisando.');
    avisar(T.acabando[0], T.acabando[1]);
  }

  salvarEstado();
}

main().catch(e => {
  log(`ERRO GERAL: ${e.message}`);
  avisar(T.erro, e.message);
});
