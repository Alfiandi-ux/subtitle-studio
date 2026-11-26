'use strict';

/* ================================================================ helpers */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const LANGUAGES = [
  ['auto', 'Deteksi otomatis'], ['id', 'Indonesia'], ['en', 'English'],
  ['ms', 'Melayu'], ['zh', '中文'], ['ja', '日本語'], ['ko', '한국어'],
  ['es', 'Español'], ['fr', 'Français'], ['de', 'Deutsch'], ['ar', 'العربية'],
  ['hi', 'हिन्दी'], ['pt', 'Português'], ['ru', 'Русский'], ['th', 'ไทย'],
  ['vi', 'Tiếng Việt'], ['tr', 'Türkçe'], ['it', 'Italiano'],
  ['nl', 'Nederlands'], ['tl', 'Filipino'], ['jv', 'Jawa'], ['su', 'Sunda'],
];

const VIEW_META = {
  media: ['Media', 'Unggah audio atau video untuk mulai.'],
  transcribe: ['Transkripsi', 'Ubah audio menjadi subtitle dengan Whisper offline atau API online.'],
  editor: ['Editor Subtitle', 'Periksa waktu, perbaiki teks, lalu ekspor SRT/VTT.'],
  tools: ['Edit Video', 'Potong, tempel subtitle, gabung, kompres, atau ekstrak audio.'],
  settings: ['Pengaturan', 'Model offline, API key, dan status sistem.'],
};

const state = {
  view: 'media',
  media: [],
  transcripts: [],
  outputs: [],
  settings: null,
  health: null,
  currentMediaId: null,
  currentTranscriptId: null,
  transcript: null,
  dirty: false,
  engine: 'offline',
  tool: 'trim',
  concatIds: [],
  trimMediaId: null,
  activeJob: null,
  jobTimer: null,
  pollBusy: false,
  openingTranscript: false,
  uploading: false,
  activeSegIndex: -1,
};

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[ch]));

const pad = (n) => String(n).padStart(2, '0');

function fmtDur(seconds) {
  const s = Number(seconds);
  if (!isFinite(s) || s <= 0) return '—';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

function fmtSrt(seconds) {
  let ms = Math.round(Math.max(0, Number(seconds) || 0) * 1000);
  const h = Math.floor(ms / 3600000); ms -= h * 3600000;
  const m = Math.floor(ms / 60000); ms -= m * 60000;
  const s = Math.floor(ms / 1000); ms -= s * 1000;
  return `${pad(h)}:${pad(m)}:${pad(s)},${String(ms).padStart(3, '0')}`;
}

function parseTime(value) {
  if (typeof value === 'number') return isFinite(value) ? Math.max(0, value) : null;
  const text = String(value ?? '').trim().replace(',', '.');
  if (!text) return null;
  if (text.includes(':')) {
    const parts = text.split(':').map(Number);
    if (parts.some((n) => !isFinite(n))) return null;
    return Math.max(0, parts.reduce((acc, n) => acc * 60 + n, 0));
  }
  const n = Number(text);
  return isFinite(n) ? Math.max(0, n) : null;
}

function fmtDate(value) {
  if (!value) return '';
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  if (isNaN(date.getTime())) return '';
  return date.toLocaleString('id-ID', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  });
}

function engineLabel(engine) {
  return { offline: 'Offline', groq: 'Groq', openai: 'OpenAI' }[engine] || engine || '—';
}

async function api(path, options = {}) {
  const opts = { ...options };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  }
  const response = await fetch(path, opts);
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { error: text }; }
  if (!response.ok) {
    throw new Error((data && (data.error || data.message)) || `HTTP ${response.status}`);
  }
  return data;
}

function toast(message, type = 'ok') {
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  node.textContent = message;
  $('#toastWrap').appendChild(node);
  setTimeout(() => node.remove(), 4600);
  node.addEventListener('click', () => node.remove());
}

function fillSelect(select, items, selected, placeholder) {
  if (!select) return;
  select.innerHTML = '';
  if (placeholder !== undefined) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = placeholder;
    select.appendChild(option);
  }
  for (const item of items) {
    const option = document.createElement('option');
    option.value = item.value;
    option.textContent = item.label;
    if (item.disabled) option.disabled = true;
    select.appendChild(option);
  }
  if (selected && items.some((item) => item.value === selected)) {
    select.value = selected;
  } else if (placeholder !== undefined) {
    select.value = '';
  }
}

function currentMedia() {
  return state.media.find((m) => m.id === state.currentMediaId) || null;
}

function editorPlayer() {
  const video = $('#edVideo');
  const audio = $('#edAudio');
  return !video.hidden && video.src ? video : (!audio.hidden && audio.src ? audio : null);
}

function toolPlayer() {
  const video = $('#vtVideo');
  const audio = $('#vtAudio');
  return !video.hidden && video.src ? video : (!audio.hidden && audio.src ? audio : null);
}

/* =================================================================== init */
document.addEventListener('DOMContentLoaded', init);

async function init() {
  fillLanguages();
  bindNav();
  bindUpload();
  bindTranscribe();
  bindEditor();
  bindTools();
  bindSettings();
  bindJobDock();
  bindGlobalKeys();

  await Promise.allSettled([
    loadHealth(),
    loadSettings(),
    loadMedia(),
    loadTranscripts(),
    loadOutputs(),
  ]);

  if (!state.currentMediaId && state.media.length) {
    state.currentMediaId = state.media[0].id;
  }
  syncAll();
  setView('media');
}

function fillLanguages() {
  const items = LANGUAGES.map(([value, label]) => ({ value, label }));
  fillSelect($('#trLanguage'), items, 'auto');
  fillSelect($('#setLanguage'), items, 'auto');
}

function setView(name) {
  state.view = name;
  $$('.nav-item').forEach((btn) => btn.classList.toggle('active', btn.dataset.view === name));
  $$('.view').forEach((view) => view.classList.toggle('active', view.id === `view-${name}`));
  const meta = VIEW_META[name] || ['Subtitle Studio', ''];
  $('#viewTitle').textContent = meta[0];
  $('#viewSub').textContent = meta[1];

  if (name === 'editor') {
    if (state.transcript) {
      renderEditor();
    } else {
      const candidate = state.transcripts.find((t) => t.media_id === state.currentMediaId)
        || state.transcripts[0];
      if (candidate) openTranscript(candidate.id, { silent: true });
      else renderEditor();
    }
  }
  if (name === 'tools') updateToolsUI();
  if (name === 'settings') renderSettings();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function bindNav() {
  $('#nav').addEventListener('click', (event) => {
    const btn = event.target.closest('.nav-item');
    if (btn) setView(btn.dataset.view);
  });
}

/* ================================================================ loading */
async function loadHealth() {
  try {
    state.health = await api('/api/health');
  } catch (err) {
    state.health = { ok: false, ffmpeg: false, whisper: false, models: [] };
    toast(`Gagal memeriksa sistem: ${err.message}`, 'error');
  }
  updateSystemBadge();
  refreshModelSelects();
  if (state.view === 'settings') renderSettings();
}

function updateSystemBadge() {
  const h = state.health || {};
  let text = 'Siap';
  let cls = 'ok';
  if (!h.ffmpeg) { text = 'FFmpeg tidak ditemukan'; cls = 'warn'; }
  else if (!h.whisper) { text = 'whisper.cpp belum siap'; cls = 'warn'; }
  else if (!h.selected_model_ready) { text = 'Model belum diunduh'; cls = 'warn'; }

  const badge = $('#sysBadge');
  badge.textContent = text;
  badge.className = `badge ${cls}`;
  $('#sideStatus').textContent = text;
  $('#sideDot').className = `status-dot ${cls}`;
}

async function loadSettings() {
  try {
    state.settings = await api('/api/settings');
  } catch (err) {
    toast(`Gagal memuat pengaturan: ${err.message}`, 'error');
    return;
  }
  state.engine = state.settings.engine || 'offline';
  renderSettings();
  updateEngineUI();
}

async function loadMedia() {
  try {
    const data = await api('/api/media');
    state.media = data.media || [];
  } catch (err) {
    toast(`Gagal memuat media: ${err.message}`, 'error');
    return;
  }
  if (state.currentMediaId && !state.media.some((m) => m.id === state.currentMediaId)) {
    state.currentMediaId = null;
  }
  if (!state.currentMediaId && state.media.length) state.currentMediaId = state.media[0].id;
  renderMedia();
  fillMediaSelects();
  updateMediaUI();
}

async function loadTranscripts() {
  try {
    const data = await api('/api/transcripts');
    state.transcripts = data.transcripts || [];
  } catch (err) {
    toast(`Gagal memuat transkrip: ${err.message}`, 'error');
    return;
  }
  if (state.currentTranscriptId
      && !state.transcripts.some((t) => t.id === state.currentTranscriptId)) {
    state.currentTranscriptId = null;
    state.transcript = null;
    state.dirty = false;
  }
  renderTranscriptList();
  fillTranscriptSelects();
}

async function loadOutputs() {
  try {
    const data = await api('/api/outputs');
    state.outputs = data.outputs || [];
  } catch (err) {
    toast(`Gagal memuat hasil: ${err.message}`, 'error');
    return;
  }
  renderOutputs();
}

/* ================================================================== media */
function renderMedia() {
  const grid = $('#mediaGrid');
  grid.innerHTML = '';
  $('#mediaCount').textContent = `${state.media.length} file`;
  $('#mediaEmpty').hidden = state.media.length > 0;

  for (const media of state.media) {
    const card = document.createElement('article');
    card.className = 'media-card';
    card.dataset.id = media.id;
    const meta = [];
    if (media.duration) meta.push(fmtDur(media.duration));
    if (media.has_video && media.width) meta.push(`${media.width}×${media.height}`);
    meta.push(media.size_label);

    card.innerHTML = `
      <div class="media-thumb">
        ${media.thumb_url
          ? `<img src="${media.thumb_url}" alt="" loading="lazy">`
          : '<div class="audio-ico">♪</div>'}
        <span class="kind">${media.has_video ? 'VIDEO' : 'AUDIO'}</span>
        <span class="dur">${fmtDur(media.duration)}</span>
      </div>
      <div class="media-body">
        <div class="media-name" title="${esc(media.name)}">${esc(media.name)}</div>
        <div class="media-meta">${esc(meta.join(' · '))}</div>
        <div class="media-actions">
          <button class="btn btn-sm" data-act="transcribe" type="button">Transkripsi</button>
          <button class="btn btn-sm" data-act="tools" type="button">Edit</button>
          <button class="btn btn-sm btn-danger" data-act="delete" type="button" title="Hapus">×</button>
        </div>
      </div>`;
    grid.appendChild(card);
  }
}

function fillMediaSelects() {
  const options = state.media.map((m) => ({
    value: m.id,
    label: `${m.name} · ${fmtDur(m.duration)}${m.has_audio ? '' : ' (tanpa audio)'}`,
  }));
  const videoOptions = state.media
    .filter((m) => m.has_video)
    .map((m) => ({ value: m.id, label: `${m.name} · ${fmtDur(m.duration)}` }));

  fillSelect($('#trMediaSelect'), options, state.currentMediaId, '— Pilih media —');
  fillSelect($('#vtMediaSelect'), options, state.currentMediaId, '— Pilih media —');
  renderConcatList(videoOptions);
}

function selectMedia(id, { notify = false } = {}) {
  if (!id) return;
  state.currentMediaId = id;
  $('#trMediaSelect').value = id;
  $('#vtMediaSelect').value = id;
  updateMediaUI();
  if (notify) toast('Media dipilih.');
}

function updateMediaUI() {
  const media = currentMedia();
  const transcribeBtn = $('#btnTranscribe');
  if (!media) {
    $('#trCurrent').textContent = 'Belum ada media dipilih.';
    transcribeBtn.disabled = true;
    $('#trimInfo').textContent = '';
    setPreviewPlayer($('#vtVideo'), $('#vtAudio'), $('#vtPlayerEmpty'), null);
    updateBurnSelect();
    return;
  }

  transcribeBtn.disabled = !media.has_audio;
  const bits = [fmtDur(media.duration), media.size_label];
  if (media.has_video && media.width) bits.push(`${media.width}×${media.height}`);
  if (media.fps) bits.push(`${media.fps} fps`);
  $('#trCurrent').textContent = `${media.name} · ${bits.join(' · ')}${media.has_audio ? '' : ' · tidak ada audio'}`;
  $('#trimInfo').textContent = `${media.name} · durasi ${fmtDur(media.duration)}${media.has_video ? ` · ${media.width}×${media.height}` : ' · audio'}`;

  setPreviewPlayer($('#vtVideo'), $('#vtAudio'), $('#vtPlayerEmpty'), media);
  if (state.trimMediaId !== media.id) {
    state.trimMediaId = media.id;
    $('#trimStart').value = fmtSrt(0);
    $('#trimEnd').value = fmtSrt(media.duration || 0);
  }
  if (media.has_video) $('#compWidth').placeholder = String(media.width || 'Otomatis');
  updateBurnSelect();
}

function setPreviewPlayer(video, audio, empty, media) {
  if (!media) {
    video.hidden = true;
    audio.hidden = true;
    video.removeAttribute('src');
    audio.removeAttribute('src');
    video.dataset.src = '';
    audio.dataset.src = '';
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  if (media.has_video) {
    video.hidden = false;
    audio.hidden = true;
    if (video.dataset.src !== media.file_url) {
      video.src = media.file_url;
      video.dataset.src = media.file_url;
    }
  } else {
    video.hidden = true;
    audio.hidden = false;
    if (audio.dataset.src !== media.file_url) {
      audio.src = media.file_url;
      audio.dataset.src = media.file_url;
    }
  }
}

function updateBurnSelect() {
  const select = $('#burnTranscript');
  const items = state.transcripts
    .filter((t) => !state.currentMediaId || t.media_id === state.currentMediaId)
    .map((t) => ({
      value: t.id,
      label: `${t.media_name || 'Tanpa media'} · ${engineLabel(t.engine)} · ${fmtDate(t.updated_at || t.created_at)}`,
    }));
  fillSelect(select, items, select.value, items.length ? '— Pilih transkrip —' : 'Belum ada transkrip untuk media ini');
  select.disabled = items.length === 0;
  $('#burnNote').textContent = items.length
    ? 'Subtitle dibakar permanen ke video. Simpan perubahan transkrip terlebih dahulu.'
    : 'Buat transkripsi untuk media ini terlebih dahulu.';
}

function bindUpload() {
  const dropzone = $('#dropzone');
  const input = $('#fileInput');

  $('#btnPickFile').addEventListener('click', (event) => {
    event.stopPropagation();
    input.click();
  });
  dropzone.addEventListener('click', (event) => {
    if (!event.target.closest('button')) input.click();
  });
  input.addEventListener('change', () => {
    if (input.files && input.files[0]) uploadFile(input.files[0]);
    input.value = '';
  });
  ['dragenter', 'dragover'].forEach((name) => {
    dropzone.addEventListener(name, (event) => {
      event.preventDefault();
      dropzone.classList.add('drag');
    });
  });
  ['dragleave', 'drop'].forEach((name) => {
    dropzone.addEventListener(name, (event) => {
      event.preventDefault();
      dropzone.classList.remove('drag');
    });
  });
  dropzone.addEventListener('drop', (event) => {
    const file = event.dataTransfer && event.dataTransfer.files[0];
    if (file) uploadFile(file);
  });

  $('#mediaGrid').addEventListener('click', async (event) => {
    const card = event.target.closest('.media-card');
    if (!card) return;
    const id = card.dataset.id;
    const button = event.target.closest('button[data-act]');
    if (button) {
      event.stopPropagation();
      if (button.dataset.act === 'transcribe') {
        selectMedia(id);
        setView('transcribe');
      } else if (button.dataset.act === 'tools') {
        selectMedia(id);
        setView('tools');
      } else if (button.dataset.act === 'delete') {
        const media = state.media.find((m) => m.id === id);
        if (!media) return;
        if (!confirm(`Hapus "${media.name}" dari pustaka? File dan thumbnail akan dihapus.`)) return;
        try {
          await api(`/api/media/${id}`, { method: 'DELETE' });
          toast('Media dihapus.');
          if (state.currentMediaId === id) state.currentMediaId = null;
          await Promise.all([loadMedia(), loadTranscripts()]);
        } catch (err) {
          toast(err.message, 'error');
        }
      }
      return;
    }
    selectMedia(id);
  });
}

function uploadFile(file) {
  if (state.uploading) {
    toast('Tunggu unggahan sebelumnya selesai.', 'warn');
    return;
  }
  state.uploading = true;
  $('#uploadProgress').hidden = false;
  $('#uploadBar').style.width = '0%';
  $('#uploadLabel').textContent = `Mengunggah ${file.name}…`;

  const form = new FormData();
  form.append('file', file);
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/upload');

  xhr.upload.addEventListener('progress', (event) => {
    if (!event.lengthComputable) return;
    const pct = Math.round((event.loaded / event.total) * 100);
    $('#uploadBar').style.width = `${pct}%`;
    $('#uploadLabel').textContent = `${pct}% · ${file.name}`;
  });

  xhr.addEventListener('load', async () => {
    state.uploading = false;
    $('#uploadProgress').hidden = true;
    let data = null;
    try { data = JSON.parse(xhr.responseText); } catch { data = null; }
    if (xhr.status >= 200 && xhr.status < 300 && data && data.media) {
      toast(`"${data.media.name}" siap ditranskripsi.`);
      await loadMedia();
      selectMedia(data.media.id);
    } else {
      toast((data && data.error) || `Unggahan gagal (HTTP ${xhr.status}).`, 'error');
    }
  });

  xhr.addEventListener('error', () => {
    state.uploading = false;
    $('#uploadProgress').hidden = true;
    toast('Koneksi ke server terputus saat mengunggah.', 'error');
  });

  xhr.send(form);
}

/* ============================================================= transcribe */
function bindTranscribe() {
  $('#trEngine').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-engine]');
    if (!button) return;
    state.engine = button.dataset.engine;
    updateEngineUI();
    api('/api/settings', {
      method: 'POST', body: JSON.stringify({ engine: state.engine }),
    }).then((settings) => { state.settings = settings; }).catch(() => {});
  });

  $('#trMediaSelect').addEventListener('change', (event) => {
    selectMedia(event.target.value);
  });
  $('#vtMediaSelect').addEventListener('change', (event) => {
    selectMedia(event.target.value);
  });
  $('#btnTranscribe').addEventListener('click', startTranscription);
}

function updateEngineUI() {
  $$('#trEngine button').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.engine === state.engine);
  });
  const offline = state.engine === 'offline';
  $('#trModelWrap').hidden = !offline;
  $('#trOnlineNote').hidden = offline;
  if (!offline) {
    const settings = state.settings || {};
    const provider = state.engine === 'groq' ? 'Groq' : 'OpenAI';
    const hasKey = state.engine === 'groq' ? settings.has_groq_key : settings.has_openai_key;
    const model = state.engine === 'groq' ? settings.groq_model : settings.openai_model;
    $('#trOnlineNote').innerHTML = hasKey
      ? `<strong>${provider}</strong> · ${esc(model || '')} · kunci API tersimpan.`
      : `<strong>${provider}</strong> · kunci API belum diisi. Buka <a href="#" data-goto-settings>Pengaturan</a> untuk menambahkannya.`;
  }
}

function refreshModelSelects() {
  const installed = (state.health && state.health.models) || [];
  const selected = (state.settings && state.settings.whisper_model) || '';
  const items = installed.map((m) => ({
    value: m.name,
    label: `${m.name.replace('ggml-', '').replace('.bin', '')} · ${m.size_label}`,
  }));
  if (!items.length) {
    fillSelect($('#trModel'), [], '', 'Belum ada model — unduh di Pengaturan');
    fillSelect($('#setModel'), [], '', 'Belum ada model');
  } else {
    fillSelect($('#trModel'), items, selected);
    fillSelect($('#setModel'), items, selected);
  }
}

async function startTranscription() {
  const media = currentMedia();
  if (!media) { toast('Pilih media terlebih dahulu.', 'warn'); return; }
  if (!media.has_audio) { toast('Media ini tidak memiliki audio.', 'warn'); return; }

  const payload = {
    media_id: media.id,
    engine: state.engine,
    language: $('#trLanguage').value || 'auto',
  };
  if (state.engine === 'offline') {
    const model = $('#trModel').value;
    if (!model) { toast('Model offline belum tersedia. Unduh dulu di Pengaturan.', 'warn'); return; }
    payload.model = model;
  }

  $('#trStatus').hidden = false;
  $('#trStatusText').textContent = 'Menyiapkan transkripsi…';
  $('#trStatusPct').textContent = '0%';
  $('#trStatusBar').style.width = '0%';
  $('#trStatusMsg').textContent = '';
  $('#trStatusBar').parentElement.classList.add('indeterminate');

  const job = await runJob($('#btnTranscribe'), '/api/transcribe', payload, {
    successMessage: 'Transkripsi selesai.',
    onDone: async (finished) => {
      if (finished.result && finished.result.transcript_id) {
        await openTranscript(finished.result.transcript_id);
      }
    },
    onError: (finished) => {
      $('#trStatusText').textContent = 'Transkripsi gagal';
      $('#trStatusMsg').textContent = finished.error || '';
    },
  });
  if (!job) {
    $('#trStatusText').textContent = 'Transkripsi tidak dimulai';
    $('#trStatusBar').parentElement.classList.remove('indeterminate');
    $('#trStatusPct').textContent = '';
  }
}

function updateTranscribeStatus(job) {
  if (!job || job.kind !== 'transcribe') return;
  $('#trStatus').hidden = false;
  $('#trStatusText').textContent = job.status === 'done'
    ? `Selesai · ${job.result && job.result.segments ? job.result.segments : 0} segmen`
    : (job.stage || 'Memproses…');
  const pct = job.progress == null ? 0 : Math.round(job.progress);
  $('#trStatusPct').textContent = job.progress == null ? '' : `${pct}%`;
  $('#trStatusBar').style.width = `${pct}%`;
  $('#trStatusBar').parentElement.classList.toggle(
    'indeterminate', job.progress == null && ['queued', 'running'].includes(job.status),
  );
  $('#trStatusMsg').textContent = job.error
    || [job.message, job.status === 'queued' ? 'menunggu antrean' : ''].filter(Boolean).join(' · ');
}

/* ================================================================= editor */
function bindEditor() {
  $('#edTranscriptSelect').addEventListener('change', (event) => {
    if (event.target.value) openTranscript(event.target.value);
  });
  $('#btnSaveTranscript').addEventListener('click', () => saveTranscript(true));
  $$('#edToolbar [data-export]').forEach((button) => {
    button.addEventListener('click', () => exportTranscript(button.dataset.export));
  });
  $$('#edToolbar [data-shift]').forEach((button) => {
    button.addEventListener('click', () => shiftAll(Number(button.dataset.shift)));
  });
  $('#btnAddSegment').addEventListener('click', addSegment);
  $('#btnSplitSegment').addEventListener('click', () => {
    const player = editorPlayer();
    if (!player) { toast('Pemutar belum siap.', 'warn'); return; }
    splitAt(player.currentTime);
  });
  $('#btnGoTranscribe').addEventListener('click', () => setView('transcribe'));

  $('#edSegments').addEventListener('input', (event) => {
    const row = event.target.closest('.seg');
    if (!row || !state.transcript) return;
    const index = Number(row.dataset.i);
    if (event.target.classList.contains('seg-text')) {
      state.transcript.segments[index].text = event.target.value;
      markDirty();
    }
  });

  $('#edSegments').addEventListener('change', (event) => {
    const row = event.target.closest('.seg');
    if (!row || !state.transcript) return;
    const index = Number(row.dataset.i);
    const isStart = event.target.classList.contains('seg-start');
    const isEnd = event.target.classList.contains('seg-end');
    if (!isStart && !isEnd) return;
    const value = parseTime(event.target.value);
    if (value == null) {
      event.target.classList.add('invalid');
      toast('Format waktu tidak valid. Contoh: 00:01:23,500', 'error');
      return;
    }
    event.target.classList.remove('invalid');
    const segment = state.transcript.segments[index];
    if (isStart) {
      segment.start = value;
      if (segment.end <= value) segment.end = value + 0.5;
    } else {
      segment.end = Math.max(value, segment.start + 0.1);
    }
    event.target.value = fmtSrt(isStart ? segment.start : segment.end);
    markDirty();
  });

  $('#edSegments').addEventListener('click', (event) => {
    const row = event.target.closest('.seg');
    if (!row || !state.transcript) return;
    const index = Number(row.dataset.i);
    const button = event.target.closest('button[data-act]');
    if (button) {
      event.stopPropagation();
      handleSegmentAction(index, button.dataset.act);
      return;
    }
    if (event.target.closest('input, textarea, button')) return;
    seekEditor(state.transcript.segments[index].start);
  });

  ['#edVideo', '#edAudio'].forEach((selector) => {
    $(selector).addEventListener('timeupdate', highlightActiveSegment);
  });
}

async function openTranscript(id, { silent = false } = {}) {
  if (state.openingTranscript) return;
  if (state.dirty && state.transcript) {
    if (state.transcript.id === id) {
      if (!confirm('Muat ulang transkrip dan buang perubahan yang belum disimpan?')) return;
    } else if (!confirm('Perubahan belum disimpan. Tetap buka transkrip lain?')) {
      return;
    }
  }
  state.openingTranscript = true;
  try {
    const data = await api(`/api/transcripts/${id}`);
    state.transcript = data.transcript;
    state.currentTranscriptId = id;
    state.dirty = false;
    state.activeSegIndex = -1;
    if (data.transcript.media) {
      state.currentMediaId = data.transcript.media.id;
      state.editorMediaId = data.transcript.media.id;
      $('#trMediaSelect').value = data.transcript.media.id;
      $('#vtMediaSelect').value = data.transcript.media.id;
      updateMediaUI();
    }
    if (silent) renderEditor();
    else setView('editor');
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    state.openingTranscript = false;
  }
}

function renderEditor() {
  const transcript = state.transcript;
  if (!transcript) {
    $('#edToolbar').hidden = true;
    $('#edEmpty').hidden = false;
    $('#edSegments').innerHTML = '';
    $('#edMediaName').textContent = 'Belum ada media';
    $('#edMediaMeta').textContent = '';
    $('#edDirty').hidden = true;
    setEditorPlayer(null, 'Pilih transkrip untuk mulai mengedit.');
    return;
  }

  $('#edEmpty').hidden = true;
  $('#edToolbar').hidden = false;
  $('#edDirty').hidden = !state.dirty;

  const media = transcript.media;
  if (media) {
    $('#edMediaName').textContent = media.name;
    const bits = [fmtDur(media.duration), media.size_label];
    if (media.has_video && media.width) bits.push(`${media.width}×${media.height}`);
    bits.push(`${transcript.segments.length} segmen`);
    $('#edMediaMeta').textContent = bits.join(' · ');
    setEditorPlayer(media, '');
  } else {
    $('#edMediaName').textContent = transcript.media_name || 'Media tidak tersedia';
    $('#edMediaMeta').textContent = 'File media sumber sudah dihapus — teks tetap bisa diedit dan diekspor.';
    setEditorPlayer(null, 'Media sumber tidak tersedia.');
  }

  const transcriptItems = state.transcripts.map((t) => ({
    value: t.id,
    label: `${t.media_name || 'Tanpa media'} · ${engineLabel(t.engine)} · ${fmtDate(t.updated_at || t.created_at)}`,
  }));
  fillSelect($('#edTranscriptSelect'), transcriptItems, transcript.id, '— Pilih transkrip —');

  const container = $('#edSegments');
  container.innerHTML = '';
  transcript.segments.forEach((segment, index) => {
    const row = document.createElement('div');
    row.className = 'seg';
    row.dataset.i = String(index);
    row.innerHTML = `
      <div class="seg-index">${String(index + 1).padStart(2, '0')}</div>
      <div class="seg-times">
        <label><span class="tiny">Mulai</span><input class="time-input seg-start" value="${fmtSrt(segment.start)}" spellcheck="false"></label>
        <label><span class="tiny">Akhir</span><input class="time-input seg-end" value="${fmtSrt(segment.end)}" spellcheck="false"></label>
      </div>
      <textarea class="seg-text" rows="2" placeholder="Teks subtitle…"></textarea>
      <div class="seg-actions">
        <button data-act="play" type="button" title="Putar dari sini">▶</button>
        <button data-act="setstart" type="button" title="Set waktu mulai dari pemutar">[</button>
        <button data-act="setend" type="button" title="Set waktu akhir dari pemutar">]</button>
        <button data-act="merge" type="button" title="Gabung dengan segmen berikutnya">⇅</button>
        <button data-act="split" type="button" title="Split di posisi pemutar">✂</button>
        <button data-act="del" type="button" title="Hapus segmen">×</button>
      </div>`;
    row.querySelector('.seg-text').value = segment.text;
    container.appendChild(row);
  });

  updateEditorStats();
  state.activeSegIndex = -1;
  highlightActiveSegment();
}

function setEditorPlayer(media, emptyText) {
  const video = $('#edVideo');
  const audio = $('#edAudio');
  const empty = $('#edPlayerEmpty');
  if (!media) {
    video.hidden = true;
    audio.hidden = true;
    video.pause();
    audio.pause();
    video.removeAttribute('src');
    audio.removeAttribute('src');
    video.dataset.src = '';
    audio.dataset.src = '';
    video.load();
    audio.load();
    empty.hidden = false;
    empty.textContent = emptyText || 'Pilih transkrip untuk mulai mengedit.';
    return;
  }
  empty.hidden = true;
  if (media.has_video) {
    video.hidden = false;
    audio.hidden = true;
    audio.pause();
    if (video.dataset.src !== media.file_url) {
      video.src = media.file_url;
      video.dataset.src = media.file_url;
      video.load();
    }
  } else {
    video.hidden = true;
    audio.hidden = false;
    video.pause();
    if (audio.dataset.src !== media.file_url) {
      audio.src = media.file_url;
      audio.dataset.src = media.file_url;
      audio.load();
    }
  }
}

function updateEditorStats() {
  if (!state.transcript) { $('#edStats').textContent = ''; return; }
  const segments = state.transcript.segments;
  const total = segments.reduce((acc, s) => acc + Math.max(0, s.end - s.start), 0);
  const chars = segments.reduce((acc, s) => acc + (s.text || '').length, 0);
  $('#edStats').textContent = `${segments.length} segmen · ${fmtDur(total)} teks · ${chars} karakter · bahasa ${state.transcript.language || 'auto'} · ${engineLabel(state.transcript.engine)}`;
}

function markDirty() {
  state.dirty = true;
  $('#edDirty').hidden = false;
  updateEditorStats();
}

function getPlayhead() {
  const player = editorPlayer() || toolPlayer();
  if (!player || !isFinite(player.currentTime)) return 0;
  return player.currentTime;
}

function seekEditor(seconds) {
  const player = editorPlayer();
  if (!player) { toast('Media sumber tidak tersedia.', 'warn'); return; }
  const target = Math.max(0, Math.min(Number(seconds) || 0, player.duration || 1e9));
  try { player.currentTime = target; } catch { /* ignore */ }
}

function handleSegmentAction(index, action) {
  if (!state.transcript) return;
  const segments = state.transcript.segments;
  const segment = segments[index];
  if (!segment) return;

  if (action === 'play') {
    const player = editorPlayer();
    seekEditor(segment.start);
    if (player) player.play().catch(() => {});
  } else if (action === 'setstart') {
    const t = getPlayhead();
    segment.start = t;
    if (segment.end <= t) segment.end = t + 0.5;
    refreshSegmentInputs(index);
    markDirty();
  } else if (action === 'setend') {
    const t = getPlayhead();
    segment.end = Math.max(t, segment.start + 0.1);
    refreshSegmentInputs(index);
    markDirty();
  } else if (action === 'merge') {
    mergeWithNext(index);
  } else if (action === 'split') {
    splitAt(getPlayhead(), index);
  } else if (action === 'del') {
    if (!confirm(`Hapus segmen ${index + 1}?`)) return;
    segments.splice(index, 1);
    renderEditor();
    markDirty();
  }
}

function refreshSegmentInputs(index) {
  const row = $(`#edSegments .seg[data-i="${index}"]`);
  const segment = state.transcript.segments[index];
  if (!row || !segment) return;
  row.querySelector('.seg-start').value = fmtSrt(segment.start);
  row.querySelector('.seg-end').value = fmtSrt(segment.end);
}

function splitAt(time, preferredIndex = null) {
  if (!state.transcript) return;
  const segments = state.transcript.segments;
  let index = preferredIndex;
  if (index == null) {
    index = segments.findIndex((s) => time > s.start + 0.1 && time < s.end - 0.1);
  }
  if (index == null || index < 0) {
    toast('Letakkan pemutar di tengah sebuah segmen untuk split.', 'warn');
    return;
  }
  const segment = segments[index];
  if (time <= segment.start + 0.1 || time >= segment.end - 0.1) {
    toast('Posisi pemutar harus di dalam segmen (bukan di tepi).', 'warn');
    return;
  }
  const words = segment.text.trim().split(/\s+/).filter(Boolean);
  if (words.length < 2) {
    toast('Teks segmen terlalu pendek untuk di-split.', 'warn');
    return;
  }
  const ratio = (time - segment.start) / (segment.end - segment.start);
  const cut = Math.max(1, Math.min(words.length - 1, Math.round(words.length * ratio)));
  const first = { start: segment.start, end: time, text: words.slice(0, cut).join(' ') };
  const second = { start: time, end: segment.end, text: words.slice(cut).join(' ') };
  segments.splice(index, 1, first, second);
  renderEditor();
  markDirty();
}

function mergeWithNext(index) {
  if (!state.transcript) return;
  const segments = state.transcript.segments;
  const segment = segments[index];
  const next = segments[index + 1];
  if (!segment || !next) { toast('Tidak ada segmen berikutnya.', 'warn'); return; }
  segment.end = Math.max(segment.end, next.end);
  segment.text = `${segment.text.trim()} ${next.text.trim()}`.trim();
  segments.splice(index + 1, 1);
  renderEditor();
  markDirty();
}

function shiftAll(delta) {
  if (!state.transcript) return;
  if (!isFinite(delta) || delta === 0) return;
  for (const segment of state.transcript.segments) {
    segment.start = Math.max(0, segment.start + delta);
    segment.end = Math.max(segment.start + 0.1, segment.end + delta);
  }
  renderEditor();
  markDirty();
  toast(`Semua segmen digeser ${delta > 0 ? '+' : ''}${delta} detik.`);
}

function addSegment() {
  if (!state.transcript) return;
  const start = getPlayhead();
  const segment = { start, end: start + 2, text: '' };
  state.transcript.segments.push(segment);
  state.transcript.segments.sort((a, b) => a.start - b.start);
  renderEditor();
  markDirty();
  const index = state.transcript.segments.indexOf(segment);
  const row = $(`#edSegments .seg[data-i="${index}"]`);
  if (row) {
    row.scrollIntoView({ block: 'center', behavior: 'smooth' });
    row.querySelector('.seg-text').focus();
  }
}

async function saveTranscript(notify = true) {
  if (!state.transcript) return false;
  const segments = state.transcript.segments
    .map((s) => ({ start: s.start, end: s.end, text: (s.text || '').trim() }))
    .filter((s) => s.text);
  if (!segments.length) {
    toast('Tambahkan minimal satu segmen berisi teks.', 'warn');
    return false;
  }
  try {
    const data = await api(`/api/transcripts/${state.transcript.id}`, {
      method: 'PUT',
      body: JSON.stringify({ segments, language: state.transcript.language }),
    });
    state.transcript = data.transcript;
    state.dirty = false;
    $('#edDirty').hidden = true;
    renderEditor();
    await loadTranscripts();
    if (notify) toast('Transkrip disimpan.');
    return true;
  } catch (err) {
    toast(err.message, 'error');
    return false;
  }
}

async function exportTranscript(format) {
  if (!state.transcript) return;
  if (state.dirty) {
    const saved = await saveTranscript(false);
    if (!saved) return;
  }
  const url = `/api/transcripts/${state.transcript.id}/export?format=${encodeURIComponent(format)}`;
  const link = document.createElement('a');
  link.href = url;
  link.download = '';
  document.body.appendChild(link);
  link.click();
  link.remove();
  toast(`Mengunduh subtitle .${format}`);
}

function highlightActiveSegment() {
  if (!state.transcript) return;
  const player = editorPlayer();
  if (!player) return;
  const t = player.currentTime;
  let active = -1;
  for (let i = 0; i < state.transcript.segments.length; i += 1) {
    const s = state.transcript.segments[i];
    if (t >= s.start && t < s.end) { active = i; break; }
  }
  if (active === state.activeSegIndex) return;
  state.activeSegIndex = active;
  $$('#edSegments .seg').forEach((row, i) => row.classList.toggle('active', i === active));
}

function renderTranscriptList() {
  const container = $('#transcriptList');
  container.innerHTML = '';
  $('#transcriptCount').textContent = state.transcripts.length
    ? `${state.transcripts.length} transkrip`
    : '';
  if (!state.transcripts.length) {
    container.innerHTML = '<div class="empty"><div class="empty-ico">◎</div><strong>Belum ada transkrip</strong><span>Pilih media lalu jalankan transkripsi untuk membuat subtitle otomatis.</span></div>';
    return;
  }

  for (const t of state.transcripts) {
    const row = document.createElement('div');
    row.className = 'list-row';
    row.innerHTML = `
      <div class="list-ico">◎</div>
      <div class="list-main">
        <div class="list-title">${esc(t.media_name || 'Tanpa media')}</div>
        <div class="list-meta">
          <span class="badge accent">${esc(engineLabel(t.engine))}</span>
          <span>${t.segment_count} segmen</span>
          <span>${esc(t.language || 'auto')}</span>
          <span>${fmtDate(t.updated_at || t.created_at)}</span>
        </div>
      </div>
      <div class="list-actions">
        <button class="btn btn-sm" data-act="edit" type="button">Edit</button>
        <button class="btn btn-sm" data-act="srt" type="button">SRT</button>
        <button class="btn btn-sm btn-danger" data-act="delete" type="button">×</button>
      </div>`;
    row.querySelector('[data-act="edit"]').addEventListener('click', () => openTranscript(t.id));
    row.querySelector('[data-act="srt"]').addEventListener('click', () => {
      const link = document.createElement('a');
      link.href = `/api/transcripts/${t.id}/export?format=srt`;
      link.download = '';
      document.body.appendChild(link);
      link.click();
      link.remove();
    });
    row.querySelector('[data-act="delete"]').addEventListener('click', async () => {
      if (!confirm(`Hapus transkrip "${t.media_name || 'tanpa media'}"?`)) return;
      try {
        await api(`/api/transcripts/${t.id}`, { method: 'DELETE' });
        toast('Transkrip dihapus.');
        if (state.currentTranscriptId === t.id) {
          state.currentTranscriptId = null;
          state.transcript = null;
          state.dirty = false;
          renderEditor();
        }
        await loadTranscripts();
      } catch (err) {
        toast(err.message, 'error');
      }
    });
    container.appendChild(row);
  }
}

function fillTranscriptSelects() {
  updateBurnSelect();
  if (state.transcript) {
    const items = state.transcripts.map((t) => ({
      value: t.id,
      label: `${t.media_name || 'Tanpa media'} · ${engineLabel(t.engine)} · ${fmtDate(t.updated_at || t.created_at)}`,
    }));
    fillSelect($('#edTranscriptSelect'), items, state.transcript.id, '— Pilih transkrip —');
  }
}

/* ================================================================== tools */
function bindTools() {
  $('#toolTabs').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-tool]');
    if (!button) return;
    state.tool = button.dataset.tool;
    $$('#toolTabs button').forEach((btn) => btn.classList.toggle('active', btn === button));
    $$('.tool-panel').forEach((panel) => {
      panel.hidden = panel.id !== `tool-${state.tool}`;
    });
  });

  $('#trimSetStart').addEventListener('click', () => {
    const player = toolPlayer();
    if (!player) { toast('Pilih media dulu.', 'warn'); return; }
    $('#trimStart').value = fmtSrt(player.currentTime);
    const start = parseTime($('#trimStart').value);
    const end = parseTime($('#trimEnd').value);
    if (end != null && start != null && end <= start) $('#trimEnd').value = fmtSrt(start + 1);
  });
  $('#trimSetEnd').addEventListener('click', () => {
    const player = toolPlayer();
    if (!player) { toast('Pilih media dulu.', 'warn'); return; }
    $('#trimEnd').value = fmtSrt(player.currentTime);
    const start = parseTime($('#trimStart').value);
    const end = parseTime($('#trimEnd').value);
    if (end != null && start != null && end <= start) $('#trimStart').value = fmtSrt(Math.max(0, end - 1));
  });

  $('#btnTrim').addEventListener('click', () => {
    const media = currentMedia();
    if (!media) { toast('Pilih media dulu.', 'warn'); return; }
    const start = parseTime($('#trimStart').value);
    const end = parseTime($('#trimEnd').value);
    if (start == null || end == null) { toast('Waktu tidak valid.', 'error'); return; }
    if (end <= start) { toast('Waktu akhir harus lebih besar dari mulai.', 'warn'); return; }
    runJob($('#btnTrim'), '/api/video/trim', {
      media_id: media.id,
      start,
      end,
      mode: $('#trimMode').value,
    }, { successMessage: 'Potongan video selesai.' });
  });

  $('#btnBurn').addEventListener('click', async () => {
    const media = currentMedia();
    const transcriptId = $('#burnTranscript').value;
    if (!media) { toast('Pilih media dulu.', 'warn'); return; }
    if (!transcriptId) { toast('Pilih transkrip untuk media ini.', 'warn'); return; }
    if (state.dirty && state.transcript && state.transcript.id === transcriptId) {
      const saved = await saveTranscript(false);
      if (!saved) return;
    }
    runJob($('#btnBurn'), '/api/video/burn', {
      media_id: media.id,
      transcript_id: transcriptId,
      style: {
        font_size: Number($('#burnFont').value) || 0,
        color: $('#burnColor').value,
        bold: $('#burnBold').checked,
        outline: Number($('#burnOutline').value) || 0,
        position: $('#burnPos').value,
        margin_v: Number($('#burnMargin').value) || 0,
      },
    }, { successMessage: 'Subtitle berhasil ditempel ke video.' });
  });

  $('#concatList').addEventListener('change', (event) => {
    const input = event.target.closest('input[type="checkbox"]');
    if (!input) return;
    const id = input.value;
    if (input.checked) {
      if (!state.concatIds.includes(id)) state.concatIds.push(id);
    } else {
      state.concatIds = state.concatIds.filter((item) => item !== id);
    }
    renderConcatList();
  });

  $('#btnConcat').addEventListener('click', () => {
    if (state.concatIds.length < 2) {
      toast('Centang minimal dua video.', 'warn');
      return;
    }
    const resolution = $('#concatRes').value;
    let width = 0;
    let height = 0;
    if (resolution !== 'auto') {
      [width, height] = resolution.split('x').map(Number);
    }
    runJob($('#btnConcat'), '/api/video/concat', {
      media_ids: state.concatIds.slice(),
      width,
      height,
      fps: Number($('#concatFps').value) || 30,
    }, { successMessage: 'Video berhasil digabung.' });
  });

  $('#compCrf').addEventListener('input', (event) => {
    $('#compCrfVal').textContent = event.target.value;
  });

  $('#btnCompress').addEventListener('click', () => {
    const media = currentMedia();
    if (!media) { toast('Pilih media dulu.', 'warn'); return; }
    if (!media.has_video) { toast('Pilih file video.', 'warn'); return; }
    runJob($('#btnCompress'), '/api/video/transform', {
      media_id: media.id,
      width: Number($('#compWidth').value) || 0,
      crf: Number($('#compCrf').value) || 23,
      preset: $('#compPreset').value,
      fps: Number($('#compFps').value) || 0,
    }, { successMessage: 'Kompres video selesai.' });
  });

  $('#btnExtract').addEventListener('click', () => {
    const media = currentMedia();
    if (!media) { toast('Pilih media dulu.', 'warn'); return; }
    if (!media.has_audio) { toast('Media ini tidak memiliki audio.', 'warn'); return; }
    runJob($('#btnExtract'), '/api/video/extract-audio', {
      media_id: media.id,
      format: $('#audioFormat').value,
    }, { successMessage: 'Audio berhasil diekstrak.' });
  });

  $('#btnRefreshOutputs').addEventListener('click', loadOutputs);
}

function updateToolsUI() {
  $('#trMediaSelect').value = state.currentMediaId || '';
  $('#vtMediaSelect').value = state.currentMediaId || '';
  updateMediaUI();
  renderConcatList();
}

function renderConcatList(videoOptions = null) {
  const container = $('#concatList');
  if (!container) return;
  const options = videoOptions || state.media
    .filter((m) => m.has_video)
    .map((m) => ({ value: m.id, label: `${m.name} · ${fmtDur(m.duration)}` }));
  const validIds = new Set(options.map((option) => option.value));
  state.concatIds = state.concatIds.filter((id) => validIds.has(id));

  container.innerHTML = '';
  if (!options.length) {
    container.innerHTML = '<div class="muted small">Belum ada video di pustaka.</div>';
    return;
  }
  for (const option of options) {
    const media = state.media.find((m) => m.id === option.value);
    if (!media) continue;
    const order = state.concatIds.indexOf(media.id);
    const label = document.createElement('label');
    label.className = 'check-row';
    label.innerHTML = `
      <input type="checkbox" value="${media.id}" ${order >= 0 ? 'checked' : ''}>
      <span class="order">${order >= 0 ? order + 1 : ''}</span>
      <span class="name">${esc(media.name)}</span>
      <span class="meta">${fmtDur(media.duration)} · ${media.width}×${media.height}</span>`;
    container.appendChild(label);
  }
}

function renderOutputs() {
  const container = $('#outputsList');
  container.innerHTML = '';
  if (!state.outputs.length) {
    container.innerHTML = '<div class="empty"><div class="empty-ico">⇩</div><strong>Belum ada hasil render</strong><span>Hasil potong, subtitle, gabung, kompres, atau ekstrak audio akan muncul di sini.</span></div>';
    return;
  }
  for (const output of state.outputs) {
    const row = document.createElement('div');
    row.className = 'list-row';
    const icon = ['mp3', 'wav', 'm4a'].includes(output.kind) ? '♪' : (['srt', 'vtt'].includes(output.kind) ? '≡' : '▶');
    row.innerHTML = `
      <div class="list-ico">${icon}</div>
      <div class="list-main">
        <div class="list-title">${esc(output.name)}</div>
        <div class="list-meta"><span>${esc(output.size_label)}</span><span>${fmtDate(output.created_at)}</span><span>${esc(output.kind.toUpperCase())}</span></div>
      </div>
      <div class="list-actions">
        <a class="btn btn-sm" href="${output.download_url}" download>Unduh</a>
        <button class="btn btn-sm btn-danger" data-act="delete" type="button">×</button>
      </div>`;
    row.querySelector('[data-act="delete"]').addEventListener('click', async () => {
      if (!confirm(`Hapus hasil "${output.name}"?`)) return;
      try {
        await api(`/api/outputs/${encodeURIComponent(output.name)}`, { method: 'DELETE' });
        toast('Hasil dihapus.');
        await loadOutputs();
      } catch (err) {
        toast(err.message, 'error');
      }
    });
    container.appendChild(row);
  }
}

/* =============================================================== settings */
function bindSettings() {
  $('#btnSaveSettings').addEventListener('click', saveSettings);
  $('#btnRefreshModels').addEventListener('click', async () => {
    await loadHealth();
    renderSettings();
    toast('Daftar model diperbarui.');
  });
  $('#modelList').addEventListener('click', async (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const name = button.dataset.name;
    if (button.dataset.action === 'use') {
      await saveModel(name);
    } else if (button.dataset.action === 'download') {
      await runJob(button, '/api/models/download', { name }, {
        successMessage: `Model ${name} berhasil diunduh.`,
        onDone: async (job) => {
          await loadHealth();
          renderSettings();
          if (job.result && job.result.model) await saveModel(job.result.model, false);
          toast('Model siap digunakan.');
        },
      });
    }
  });

  document.addEventListener('click', (event) => {
    if (event.target.closest('[data-goto-settings]')) {
      event.preventDefault();
      setView('settings');
    }
  });
}

function renderSettings() {
  const s = state.settings;
  if (!s) return;
  $('#setEngine').value = s.engine || 'offline';
  $('#setLanguage').value = s.language || 'auto';
  if (!$$('#setThreads option').some((option) => Number(option.value) === Number(s.threads))) {
    const option = document.createElement('option');
    option.textContent = String(s.threads);
    $('#setThreads').appendChild(option);
  }
  $('#setThreads').value = String(s.threads || 4);
  refreshModelSelects();
  if (s.whisper_model) $('#setModel').value = s.whisper_model;

  $('#setGroqKey').value = '';
  $('#setOpenaiKey').value = '';
  $('#setGroqKey').placeholder = s.has_groq_key ? '•••••••••••• (tersimpan)' : 'gsk_…';
  $('#setOpenaiKey').placeholder = s.has_openai_key ? '•••••••••••• (tersimpan)' : 'sk-…';
  $('#groqState').textContent = s.has_groq_key ? 'Kunci tersimpan di perangkat.' : 'Belum ada kunci.';
  $('#openaiState').textContent = s.has_openai_key ? 'Kunci tersimpan di perangkat.' : 'Belum ada kunci.';

  renderModelList();
  renderSysInfo();
}

function renderModelList() {
  const container = $('#modelList');
  const health = state.health || {};
  const installed = health.models || [];
  const settings = state.settings || {};
  container.innerHTML = '';

  if (installed.length) {
    for (const model of installed) {
      const active = settings.whisper_model === model.name;
      const row = document.createElement('div');
      row.className = 'model-row';
      row.innerHTML = `
        <span class="name">${esc(model.name)}</span>
        <span class="meta">${esc(model.size_label)}</span>
        ${active ? '<span class="badge ok">Aktif</span>' : `<button class="btn btn-sm" data-action="use" data-name="${esc(model.name)}" type="button">Gunakan</button>`}`;
      container.appendChild(row);
    }
  }

  const installedNames = new Set(installed.map((m) => m.name));
  const missing = [
    ['ggml-tiny.bin', 'Tiny · 75 MB'],
    ['ggml-base.bin', 'Base · 142 MB'],
    ['ggml-small.bin', 'Small · 466 MB'],
    ['ggml-medium.bin', 'Medium · 1,5 GB'],
    ['ggml-large-v3-turbo.bin', 'Large v3 Turbo · 1,6 GB'],
  ].filter(([name]) => !installedNames.has(name));

  if (missing.length) {
    const divider = document.createElement('div');
    divider.className = 'muted small';
    divider.style.margin = '8px 2px 2px';
    divider.textContent = 'Tersedia untuk diunduh:';
    container.appendChild(divider);
    for (const [name, label] of missing) {
      const row = document.createElement('div');
      row.className = 'model-row';
      row.innerHTML = `
        <span class="name">${esc(name)}</span>
        <span class="meta">${esc(label)}</span>
        <button class="btn btn-sm" data-action="download" data-name="${esc(name)}" type="button">Unduh</button>`;
      container.appendChild(row);
    }
  }

  if (!installed.length && !missing.length) {
    container.innerHTML = '<div class="muted small">Tidak ada model. Periksa folder model whisper.cpp.</div>';
  }
}

function renderSysInfo() {
  const h = state.health;
  if (!h) { $('#sysInfo').innerHTML = '<div class="muted small">Memuat…</div>'; return; }
  const items = [
    ['FFmpeg', h.ffmpeg ? 'Tersedia' : 'Tidak ditemukan', h.ffmpeg],
    ['whisper.cpp', h.whisper ? 'Siap' : 'Belum dibangun', h.whisper],
    ['Model aktif', `${h.selected_model || '—'}${h.selected_model_ready ? '' : ' · belum diunduh'}`, h.selected_model_ready],
    ['Folder model', h.models_dir || '—', null],
    ['Folder data', h.data_dir || '—', null],
  ];
  $('#sysInfo').innerHTML = items.map(([key, value, ok]) => `
    <div class="sys-item">
      <div class="k">${esc(key)}</div>
      <div class="v ${ok === true ? 'ok' : (ok === false ? 'bad' : '')}">${esc(value)}</div>
    </div>`).join('');
}

async function saveSettings() {
  const payload = {
    engine: $('#setEngine').value,
    language: $('#setLanguage').value,
    threads: Number($('#setThreads').value) || 4,
    whisper_model: $('#setModel').value || undefined,
  };
  const groqKey = $('#setGroqKey').value.trim();
  const openaiKey = $('#setOpenaiKey').value.trim();
  if (groqKey) payload.groq_key = groqKey;
  if (openaiKey) payload.openai_key = openaiKey;

  try {
    state.settings = await api('/api/settings', {
      method: 'POST', body: JSON.stringify(payload),
    });
    state.engine = state.settings.engine || 'offline';
    updateEngineUI();
    renderSettings();
    refreshModelSelects();
    toast('Pengaturan disimpan.');
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function saveModel(name, notify = true) {
  try {
    state.settings = await api('/api/settings', {
      method: 'POST', body: JSON.stringify({ whisper_model: name }),
    });
    refreshModelSelects();
    renderSettings();
    if (notify) toast(`Model aktif: ${name}`);
  } catch (err) {
    toast(err.message, 'error');
  }
}

/* ==================================================================== job */
function bindJobDock() {
  $('#jobDockCancel').addEventListener('click', async () => {
    if (!state.activeJob) return;
    const id = state.activeJob.id;
    try {
      await api(`/api/jobs/${id}/cancel`, { method: 'POST' });
      toast('Permintaan pembatalan dikirim.', 'warn');
    } catch (err) {
      toast(err.message, 'error');
    }
  });
}

async function runJob(button, url, payload, options = {}) {
  if (state.activeJob && ['queued', 'running'].includes(state.activeJob.status)) {
    toast('Tunggu job yang sedang berjalan selesai dulu.', 'warn');
    return null;
  }
  if (button) button.disabled = true;
  try {
    const data = await api(url, { method: 'POST', body: JSON.stringify(payload) });
    trackJob(data.job, { ...options, button });
    return data.job;
  } catch (err) {
    if (button) button.disabled = false;
    toast(err.message, 'error');
    return null;
  }
}

function trackJob(job, options = {}) {
  state.activeJob = { ...job, options };
  showJobDock();
  updateJobDock(job);
  updateTranscribeStatus(job);
  clearInterval(state.jobTimer);
  state.jobTimer = setInterval(pollJob, 1000);
}

async function pollJob() {
  if (!state.activeJob || state.pollBusy) return;
  state.pollBusy = true;
  try {
    const data = await api(`/api/jobs/${state.activeJob.id}`);
    const job = data.job;
    state.activeJob = { ...state.activeJob, ...job };
    updateJobDock(job);
    updateTranscribeStatus(job);
    if (['done', 'error', 'cancelled'].includes(job.status)) {
      clearInterval(state.jobTimer);
      state.jobTimer = null;
      await finishJob(job);
    }
  } catch (err) {
    clearInterval(state.jobTimer);
    state.jobTimer = null;
    const options = (state.activeJob && state.activeJob.options) || {};
    if (options.button) options.button.disabled = false;
    state.activeJob = null;
    hideJobDock();
    toast(`Gagal memantau job: ${err.message}`, 'error');
  } finally {
    state.pollBusy = false;
  }
}

async function finishJob(job) {
  const options = (state.activeJob && state.activeJob.options) || {};
  if (options.button) options.button.disabled = false;

  if (job.status === 'done') {
    toast(options.successMessage || `Selesai: ${job.label}`);
    await loadOutputs();
    if (job.kind === 'transcribe') await loadTranscripts();
    if (job.kind === 'model') {
      await loadHealth();
      renderSettings();
      refreshModelSelects();
    }
    if (options.onDone) {
      try { await options.onDone(job); } catch (err) { toast(err.message, 'error'); }
    }
  } else if (job.status === 'error') {
    toast(job.error || 'Job gagal.', 'error');
    if (options.onError) {
      try { options.onError(job); } catch { /* ignore */ }
    }
  } else {
    toast('Job dibatalkan.', 'warn');
  }

  const finishedId = job.id;
  setTimeout(() => {
    if (state.activeJob && state.activeJob.id === finishedId) {
      hideJobDock();
      state.activeJob = null;
    }
  }, 3200);
}

function showJobDock() {
  $('#jobDock').hidden = false;
}

function hideJobDock() {
  $('#jobDock').hidden = true;
}

function updateJobDock(job) {
  const running = ['queued', 'running'].includes(job.status);
  $('#jobDockTitle').textContent = job.label || 'Job';
  const pct = job.progress == null ? 0 : Math.round(job.progress);
  $('#jobDockPct').textContent = job.progress == null ? '' : `${pct}%`;
  const bar = $('#jobDockBar');
  bar.style.width = `${pct}%`;
  bar.parentElement.classList.toggle('indeterminate', job.progress == null && running);
  const dot = $('#jobDock .job-dot');
  dot.className = `job-dot${job.status === 'done' ? ' done' : ''}${job.status === 'error' ? ' error' : ''}`;
  $('#jobDockMsg').textContent = job.error
    || [job.stage, job.message].filter(Boolean).join(' · ')
    || job.status;
  $('#jobDockCancel').hidden = !running;
}

/* ================================================================ global */
function bindGlobalKeys() {
  window.addEventListener('beforeunload', (event) => {
    if (!state.dirty) return;
    event.preventDefault();
    event.returnValue = '';
  });
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      if (state.view === 'editor' && state.transcript) {
        event.preventDefault();
        saveTranscript(true);
      }
    }
  });
}

function syncAll() {
  fillMediaSelects();
  updateMediaUI();
  refreshModelSelects();
  renderTranscriptList();
  fillTranscriptSelects();
  renderOutputs();
  if (state.view === 'editor') renderEditor();
}
