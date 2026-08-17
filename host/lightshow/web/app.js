/* Lightshow — Bedienpult.
 *
 * No framework, no build step: the bridge serves three files and runs on the
 * Python standard library alone.
 *
 * The idea this interface is built around: an application that controls light
 * should show light. The effect engine of the airborne firmware is ported to
 * JavaScript below, faithfully enough that the strip you see on screen is the
 * pattern the aircraft will fly. It drives the block previews in the editor,
 * the effect picker and the whole Bühne view. Numbers support that picture
 * instead of replacing it.
 *
 * Two rules keep the editor honest:
 *
 *  - Positions are measured against the timeline's bounding box, never against
 *    `offsetX`, which is relative to whatever element the pointer happened to
 *    be over -- a ruler tick or an existing clip as often as the lane itself.
 *  - The editor may not produce a project the bridge would refuse to save.
 *    Blocks on one light track are clamped against their neighbours, and fades
 *    are kept inside their block, because a zone shows one effect at a time.
 */

'use strict';

/* ====================================================================== base */

const $ = (id) => document.getElementById(id);

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) =>
  ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const round3 = (value) => Math.round(value * 1000) / 1000;

function fmtTime(seconds) {
  const total = Math.max(0, seconds || 0);
  const minutes = Math.floor(total / 60);
  const rest = total - minutes * 60;
  return `${minutes}:${rest.toFixed(1).padStart(4, '0').replace('.', ',')}`;
}

async function api(url, options) {
  try {
    const response = await fetch(url, options);
    return await response.json();
  } catch (error) {
    return {ok: false, error: `Bridge nicht erreichbar (${error.message})`};
  }
}

const post = (url, body) => api(url, {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify(body || {}),
});

function toast(text, kind = '', timeout = 6000) {
  const box = document.createElement('div');
  box.className = 'toast' + (kind ? ' ' + kind : '');
  const close = document.createElement('button');
  close.textContent = '×';
  close.setAttribute('aria-label', 'Schließen');
  close.onclick = () => box.remove();
  box.append(close, document.createTextNode(text));
  $('toasts').append(box);
  if (timeout) setTimeout(() => box.remove(), timeout);
  return box;
}

function note(container, messages, kind = 'err') {
  const list = (messages || []).filter(Boolean);
  container.classList.toggle('hidden', !list.length);
  container.className = list.length ? `note ${kind}` : 'note hidden';
  container.innerHTML = list.map(esc).join('<br>');
}

/* ============================================================ LED previews */

/* The effect engine lives in effects.js -- a faithful port of the airborne
 * firmware, cross-checked against the real C by the test suite. Everything
 * below only paints what it produces. */

/* ------------------------------------------------------------- LED canvas -- */

/* Every preview registers itself here and one animation loop drives all of
 * them. Separate timers per canvas would drift apart and cost far more. */
const PREVIEWS = new Set();

function preview(canvas, provider, pixelCount = 28) {
  const entry = {canvas, provider, count: pixelCount, buffer: null};
  PREVIEWS.add(entry);
  return entry;
}

function dropPreviews(root) {
  for (const entry of [...PREVIEWS])
    if (!entry.canvas.isConnected || (root && root.contains(entry.canvas)))
      PREVIEWS.delete(entry);
}

function drawStrip(canvas, pixels, count) {
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;

  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
  }

  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const cell = width / count;
  const centre = height / 2;

  // Below roughly four pixels per LED, circles turn into noise -- draw bars.
  if (cell < 4) {
    for (let i = 0; i < count; i++) {
      ctx.fillStyle = `rgb(${pixels[i * 3]},${pixels[i * 3 + 1]},${pixels[i * 3 + 2]})`;
      ctx.fillRect(i * cell, height * 0.18, Math.ceil(cell), height * 0.64);
    }
    return;
  }

  const radius = Math.min(cell * 0.34, height * 0.3);
  const circles = (grow, alpha) => {
    ctx.globalAlpha = alpha;
    for (let i = 0; i < count; i++) {
      const r = pixels[i * 3];
      const g = pixels[i * 3 + 1];
      const b = pixels[i * 3 + 2];
      if (!r && !g && !b) continue;
      ctx.fillStyle = `rgb(${r},${g},${b})`;
      ctx.beginPath();
      ctx.arc(i * cell + cell / 2, centre, radius * grow, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  };

  // Dark sockets, so an unlit strip still reads as a strip.
  ctx.fillStyle = 'rgba(255,255,255,.05)';
  for (let i = 0; i < count; i++) {
    ctx.beginPath();
    ctx.arc(i * cell + cell / 2, centre, radius, 0, Math.PI * 2);
    ctx.fill();
  }

  // One blurred pass for the bloom, one sharp pass for the LED itself. Doing
  // it per pixel with radial gradients looks the same and costs far more.
  const canBlur = 'filter' in ctx;
  if (canBlur) {
    ctx.filter = `blur(${Math.max(2, radius * 0.9).toFixed(1)}px)`;
    circles(1.5, 0.75);
    ctx.filter = 'none';
  }
  circles(1, 1);
}

let lastFrame = 0;
function animate(now) {
  requestAnimationFrame(animate);
  if (now - lastFrame < 33) return;                 // ~30 fps is plenty
  lastFrame = now;

  for (const entry of PREVIEWS) {
    const canvas = entry.canvas;
    if (!canvas.isConnected) { PREVIEWS.delete(entry); continue; }
    if (!canvas.offsetParent) continue;             // in a hidden view
    const show = entry.provider();
    if (!show) continue;
    const options = {max: show.max ?? 255, out: entry.buffer};
    entry.buffer = show.failsafe
      ? renderFailsafe(now, entry.count, options)
      : renderEffect(show, now, entry.count, options);
    drawStrip(canvas, entry.buffer, entry.count);
  }
}
requestAnimationFrame(animate);

/* ===================================================================== state */

let STATE = null;         // last frame from /api/events
let CONFIG = null;        // working copy of show.yaml
let LOCKED = false;
let PROJ = null;
let PEAKS = [];
let CUES = [];
let SEL = null;           // {kind: 'block'|'clip'|'track', track, item}
let DIRTY = false;
let VIEW = 'show';

let PPS = 40;             // pixels per second
let SNAP = true;
let POSITION = 0;
let SEEK_HINT = null;
let FOLLOW = true;

const ITEM_EL = new Map();

const cueName = (index) => CUES[index] || `Effekt ${index}`;

/* ===================================================================== theme */

let theme = 'dark';
try { theme = localStorage.getItem('lightshow-theme') || 'dark'; } catch { /* ignore */ }

function applyTheme(mode) {
  document.documentElement.setAttribute('data-theme', mode);
  try { localStorage.setItem('lightshow-theme', mode); } catch { /* private mode */ }
  $('btn-theme').title = mode === 'dark' ? 'Dunkel — umschalten auf hell'
                                         : 'Hell — umschalten auf dunkel';
}
applyTheme(theme);
$('btn-theme').onclick = () => { theme = theme === 'dark' ? 'light' : 'dark'; applyTheme(theme); };
$('btn-help').onclick = () => $('help').showModal();

/* ===================================================================== views */

const VIEWS = ['show', 'stage', 'models', 'wiring'];

function showView(name) {
  VIEW = name;
  document.querySelectorAll('.rail button.nav').forEach((button) =>
    button.setAttribute('aria-selected', String(button.dataset.view === name)));
  VIEWS.forEach((other) => $('view-' + other).classList.toggle('hidden', other !== name));
  $('project-bar').classList.toggle('hidden', name !== 'show');

  if (name === 'wiring') { fillWiringModels(); loadWiring(); refreshToolchain(); }
  if (name === 'stage' && STATE) renderStage(STATE);
  if (name === 'show') layoutTimeline();
}

document.querySelectorAll('.rail button.nav').forEach((button) => {
  button.onclick = () => showView(button.dataset.view);
});

/* ================================================================== projects */

let applyTimer = null;
let lastApplyError = '';

/**
 * Marks the project changed and pushes the edit to the bridge.
 *
 * The bridge mixes the audio once and evaluates the light timeline against
 * that mix. An edit that never reaches it is an edit that is never heard: a
 * clip moved on screen and kept playing from its old place, and a track's
 * volume did nothing at all. Pushing here -- debounced, so a drag stays
 * smooth -- keeps what you hear equal to what you see. Writing to disk is
 * still a separate act.
 */
function markDirty(dirty = true) {
  DIRTY = dirty;
  $('btn-project-save').textContent = dirty ? 'Speichern •' : 'Speichern';
  if (!dirty) return;
  clearTimeout(applyTimer);
  applyTimer = setTimeout(pushEdit, 300);
}

async function pushEdit() {
  if (!PROJ) return;
  const answer = await post('/api/project/apply', {project: PROJ});
  if (answer.ok) { lastApplyError = ''; return; }
  // A rejected edit would otherwise repeat its complaint on every keystroke.
  if (answer.error !== lastApplyError) {
    lastApplyError = answer.error;
    toast(answer.error, 'err', 8000);
  }
}

window.addEventListener('beforeunload', (event) => {
  if (!DIRTY) return;
  event.preventDefault();
  event.returnValue = '';
});

/** Points the selector at the open project, adding it if the list is stale. */
function syncProjectSelect(dir) {
  if (!dir) return;
  const select = $('project-select');
  if (![...select.options].some((option) => option.value === dir)) {
    const option = document.createElement('option');
    option.value = dir;
    option.textContent = dir;
    select.append(option);
  }
  select.value = dir;
}

async function loadProjects(select) {
  const answer = await api('/api/projects');
  const list = answer.projects || [];
  $('project-select').innerHTML = list.length
    ? list.map((entry) => `<option value="${esc(entry.dir)}">${esc(entry.name)}</option>`).join('')
    : '<option value="">— keine Projekte —</option>';
  if (select) $('project-select').value = select;
}

function selectionAddress() {
  if (!SEL || !PROJ) return null;
  if (SEL.kind === 'track') {
    const audio = PROJ.audio_tracks.indexOf(SEL.track);
    return audio >= 0
      ? {kind: 'track', list: 'audio', track: audio}
      : {kind: 'track', list: 'light', track: PROJ.light_tracks.indexOf(SEL.track)};
  }
  const clip = SEL.kind === 'clip';
  const tracks = clip ? PROJ.audio_tracks : PROJ.light_tracks;
  const trackIndex = tracks.indexOf(SEL.track);
  if (trackIndex < 0) return null;
  const items = clip ? SEL.track.clips : SEL.track.blocks;
  return {kind: SEL.kind, track: trackIndex, item: items.indexOf(SEL.item)};
}

function restoreSelection(address) {
  if (!address || !PROJ) return;
  if (address.kind === 'track') {
    const tracks = address.list === 'audio' ? PROJ.audio_tracks : PROJ.light_tracks;
    if (tracks[address.track]) SEL = {kind: 'track', track: tracks[address.track]};
    return;
  }
  const clip = address.kind === 'clip';
  const track = (clip ? PROJ.audio_tracks : PROJ.light_tracks)[address.track];
  if (!track) return;
  const item = (clip ? track.clips : track.blocks)[address.item];
  if (item) SEL = {kind: address.kind, track, item};
}

function applyProject(payload) {
  const previous = selectionAddress();

  if (!payload) {
    PROJ = null; PEAKS = []; SEL = null;
    markDirty(false);
    buildTimeline();
    renderInspector();
    return;
  }

  PROJ = payload.data;
  PEAKS = payload.peaks || [];
  CUES = payload.cue_names || [];
  markDirty(false);
  syncProjectSelect(payload.dir);

  const messages = [...(payload.warnings || []), ...(payload.audio_messages || [])];
  if (messages.length) toast(messages.join(' · '), 'err', 12000);

  SEL = null;
  restoreSelection(previous);
  buildTimeline();
  renderInspector();
}

async function loadProject() {
  applyProject((await api('/api/project')).project);
}

$('btn-project-open').onclick = async () => {
  const dir = $('project-select').value;
  if (!dir) return;
  if (DIRTY && !confirm('Es gibt ungespeicherte Änderungen. Trotzdem ein anderes Projekt öffnen?'))
    return;
  markDirty(false);
  const answer = await post('/api/project/open', {dir});
  if (answer.ok) applyProject(answer.project);
  else toast(answer.error, 'err');
};

$('btn-project-new').onclick = async () => {
  const name = (prompt('Name des neuen Projekts:', 'Nachtflug') || '').trim();
  if (!name) return;
  const answer = await post('/api/project/new', {name});
  if (!answer.ok) return toast(answer.error, 'err');
  await loadProjects();
  applyProject(answer.project);
  toast(`Projekt „${name}“ angelegt.`, 'ok', 3000);
};

async function saveProject(quiet = false) {
  if (!PROJ) return false;
  const answer = await post('/api/project', {project: PROJ});
  if (!answer.ok) { toast(answer.error, 'err', 12000); return false; }
  applyProject(answer.project);
  if (!quiet) toast('Gespeichert.', 'ok', 2000);
  return true;
}

$('btn-project-save').onclick = () => saveProject();

/* ============================================================ timeline model */

const MIN_LENGTH = 0.1;

function laneList() {
  if (!PROJ) return [];
  return [
    ...PROJ.audio_tracks.map((track, index) => ({kind: 'audio', track, index})),
    ...PROJ.light_tracks.map((track, index) => ({kind: 'light', track, index})),
  ];
}

function itemsOf(lane) {
  return lane.kind === 'audio' ? lane.track.clips : lane.track.blocks;
}

function laneOf(track) {
  return laneList().find((lane) => lane.track === track) || null;
}

function clipLength(track, clip) {
  if (clip.duration_s > 0) return clip.duration_s;
  const trackIndex = PROJ.audio_tracks.indexOf(track);
  const info = PEAKS.find((peak) =>
    peak.track === trackIndex && peak.clip === track.clips.indexOf(clip));
  return info ? info.duration_s : 0;
}

function projectEnd() {
  let end = 0;
  if (!PROJ) return end;
  for (const track of PROJ.audio_tracks)
    for (const clip of track.clips) end = Math.max(end, clip.start_s + clipLength(track, clip));
  for (const track of PROJ.light_tracks)
    for (const block of track.blocks) end = Math.max(end, block.start_s + block.duration_s);
  return end;
}

const timelineSpan = () => Math.max(30, projectEnd() + 15);

const gridStep = () =>
  PPS >= 120 ? 0.05 : PPS >= 50 ? 0.1 : PPS >= 20 ? 0.25 : PPS >= 8 ? 1 : 5;

function snapTime(seconds, bypass) {
  if (!SNAP || bypass) return round3(seconds);
  const step = gridStep();
  return round3(Math.round(seconds / step) * step);
}

/** Seconds at a screen position, measured against the lane area itself. */
function timeAtClientX(clientX) {
  const box = $('tl-lanes').getBoundingClientRect();
  return Math.max(0, (clientX - box.left) / PPS);
}

/* Colour of a block in the timeline: the hue it actually sends. */
function blockColour(block, alpha = 1) {
  if (!block.cue) return 'var(--surface-3)';
  const [r, g, b] = hsv(block.hue, 255);
  const level = 0.35 + (block.brightness / 255) * 0.5;
  return `rgba(${Math.round(r * level)},${Math.round(g * level)},${Math.round(b * level)},${alpha})`;
}

/* ========================================================= timeline building */

function buildTimeline() {
  const heads = $('tl-heads');
  const lanes = $('tl-lanes');
  dropPreviews(lanes);
  ITEM_EL.clear();
  heads.innerHTML = '';
  lanes.innerHTML = '';

  const lanesList = laneList();
  $('editor').classList.toggle('empty-project', !PROJ);

  if (!PROJ) {
    lanes.innerHTML = '<div class="empty">Kein Projekt geöffnet — oben eines auswählen '
      + 'und <b>Öffnen</b>, oder <b>Neu</b> anlegen.</div>';
    layoutTimeline();
    return;
  }
  if (!lanesList.length) {
    lanes.innerHTML = '<div class="empty">Dieses Projekt hat noch keine Spuren. '
      + 'Links oben <b>+A</b> oder <b>+L</b>.</div>';
  }

  for (const lane of lanesList) {
    heads.append(buildHead(lane));
    lanes.append(buildLane(lane));
  }
  layoutTimeline();
}

function buildHead(lane) {
  const head = document.createElement('div');
  head.className = 'head';
  head.title = 'Klicken für die Spureinstellungen';
  head.classList.toggle('muted', lane.kind === 'audio' && lane.track.mute);
  if (SEL && SEL.kind === 'track' && SEL.track === lane.track) head.classList.add('sel');

  const name = document.createElement('div');
  name.className = 'hn';
  name.textContent = lane.kind === 'audio'
    ? (lane.track.name || `Audio ${lane.index + 1}`)
    : (lane.track.name || lane.track.model);

  const sub = document.createElement('div');
  sub.className = 'hs';

  if (lane.kind === 'audio') {
    const gain = lane.track.gain_db;
    sub.append(gain ? `${gain > 0 ? '+' : ''}${gain} dB` : 'Audio');
    const mute = document.createElement('button');
    mute.className = 'mute' + (lane.track.mute ? ' on' : '');
    mute.textContent = 'M';
    mute.title = 'Stumm';
    mute.onclick = (event) => {
      event.stopPropagation();
      lane.track.mute = !lane.track.mute;
      markDirty();
      buildTimeline();
      renderInspector();
    };
    sub.append(mute);
  } else {
    const model = STATE && STATE.models.find((entry) => entry.name === lane.track.model);
    const outputs = zoneOutputs(lane.track);
    if (!model) sub.append('⚠ unbekanntes Modell');
    else if (outputs && outputs.strips.length) {
      sub.append(outputs.strips.map((strip) => strip.name).join(' + '));
      head.title = `Sender ${model.tx_port + 1} · Kanal ${outputs.base_channel}`
        + `–${outputs.base_channel + 3} · ${describeOutputs(outputs)}`;
    } else sub.append(`Sender ${model.tx_port + 1}`);
    if (model && model.zones > 1) sub.append(` · Z${lane.track.zone + 1}`);
  }

  head.append(name, sub);
  head.onclick = () => selectTrack(lane.track);
  return head;
}

function buildLane(lane) {
  const element = document.createElement('div');
  element.className = 'lane' + (lane.kind === 'audio' ? ' audio' : '');
  element.classList.toggle('muted', lane.kind === 'audio' && lane.track.mute);
  element.classList.toggle('nogrid', !SNAP);

  for (const item of itemsOf(lane)) {
    const node = buildItem(lane, item);
    ITEM_EL.set(item, node);
    element.append(node);
  }

  if (lane.kind === 'audio') {
    wireDrop(element, lane);
    element.classList.toggle('vacant', !lane.track.clips.length);
    element.onclick = (event) => {
      if (event.target !== element || lane.track.clips.length) return;
      pickAudio(lane, snapTime(timeAtClientX(event.clientX), event.altKey));
    };
  }
  element.onpointerdown = (event) => { if (event.target === element) selectNothing(); };
  return element;
}

function buildItem(lane, item) {
  const node = document.createElement('div');
  node.className = 'item' + (lane.kind === 'audio' ? ' clip' : '');

  const parts = {};
  if (lane.kind === 'light') {
    // The block shows its own effect running. That is the whole point: you
    // recognise a strobe from across the room without reading the label.
    parts.canvas = document.createElement('canvas');
    parts.canvas.className = 'mini';
    node.append(parts.canvas);
    preview(parts.canvas, () => ({
      cue: item.cue, hue: item.hue, param: item.param,
      brightness: Math.round(item.brightness * 0.9),
    }), 20);
  }

  parts.cap = document.createElement('div');
  parts.cap.className = 'cap';
  parts.cap2 = document.createElement('div');
  parts.cap2.className = 'cap2';
  parts.fadeIn = document.createElement('div');
  parts.fadeIn.className = 'fade';
  parts.fadeOut = document.createElement('div');
  parts.fadeOut.className = 'fade o';
  const left = document.createElement('div');
  left.className = 'grip l';
  const right = document.createElement('div');
  right.className = 'grip r';
  node.append(parts.cap, parts.cap2, parts.fadeIn, parts.fadeOut, left, right);

  node._parts = parts;
  node._lane = lane;
  node._item = item;
  node.onpointerdown = (event) => startDrag(event, node);
  layoutItem(node);
  return node;
}

function layoutItem(node) {
  const item = node._item;
  const lane = node._lane;
  const length = lane.kind === 'audio' ? clipLength(lane.track, item) : item.duration_s;
  const width = Math.max(4, length * PPS);
  const parts = node._parts;

  node.style.left = (item.start_s * PPS).toFixed(1) + 'px';
  node.style.width = width.toFixed(1) + 'px';
  node.classList.toggle('sel', !!(SEL && SEL.item === item));

  if (lane.kind === 'audio') {
    parts.cap.textContent = item.file.replace(/^audio\//, '');
    parts.cap2.textContent = fmtTime(length)
      + (item.gain_db ? ` · ${item.gain_db > 0 ? '+' : ''}${item.gain_db} dB` : '');
    drawWave(node, lane, item);
  } else {
    node.style.background = blockColour(item, 0.35);
    parts.cap.textContent = item.label || cueName(item.cue);
    parts.cap2.textContent = width > 92
      ? `${fmtTime(length)} · ${Math.round(item.brightness / 255 * 100)} %` : '';
  }

  parts.fadeIn.style.width = item.fade_in_s > 0
    ? Math.min(width, item.fade_in_s * PPS).toFixed(1) + 'px' : '0';
  parts.fadeOut.style.width = item.fade_out_s > 0
    ? Math.min(width, item.fade_out_s * PPS).toFixed(1) + 'px' : '0';
}

function drawWave(node, lane, clip) {
  if (node._wave) return;
  const trackIndex = PROJ.audio_tracks.indexOf(lane.track);
  const info = PEAKS.find((peak) =>
    peak.track === trackIndex && peak.clip === lane.track.clips.indexOf(clip));
  if (!info || info.peaks.length < 2) return;

  const last = info.peaks.length - 1;
  const top = info.peaks.map((value, index) =>
    `${(index / last * 100).toFixed(2)},${(50 - value * 46).toFixed(1)}`).join(' ');
  const bottom = info.peaks.map((value, index) =>
    `${((last - index) / last * 100).toFixed(2)},${(50 + value * 46).toFixed(1)}`).join(' ');

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'wave');
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.innerHTML = `<polygon points="${top} ${bottom}" fill="currentColor"/>`;
  node.prepend(svg);
  node._wave = svg;
}

const refreshItem = (item) => { const node = ITEM_EL.get(item); if (node) layoutItem(node); };

/** Redraws one track head in place, without rebuilding the timeline. */
function refreshHead(track) {
  const lanes = laneList();
  const index = lanes.findIndex((lane) => lane.track === track);
  const heads = $('tl-heads').children;
  if (index < 0 || !heads[index]) return;
  const head = buildHead(lanes[index]);
  head.classList.toggle('sel', !!(SEL && SEL.kind === 'track' && SEL.track === track));
  heads[index].replaceWith(head);
  const lane = $('tl-lanes').children[index];
  if (lane) lane.classList.toggle('muted', lanes[index].kind === 'audio' && track.mute);
}

/** Widths, ruler and markers. Everything that depends on the zoom level. */
function layoutTimeline() {
  const span = timelineSpan();
  const width = Math.max(600, span * PPS);
  $('tl-grid').style.setProperty('--body-w', width + 'px');
  $('tl-lanes').style.setProperty('--grid-step', (gridStep() * PPS) + 'px');

  const step = PPS >= 100 ? 1 : PPS >= 45 ? 2 : PPS >= 20 ? 5 : PPS >= 8 ? 15 : 30;
  let html = '';
  for (let t = 0; t <= span; t += step) {
    html += `<div class="t" style="left:${(t * PPS).toFixed(1)}px"><span>${fmtTime(t)}</span></div>`;
    if (PPS >= 20 && t + step / 2 <= span)
      html += `<div class="t m" style="left:${((t + step / 2) * PPS).toFixed(1)}px"></div>`;
  }
  $('tl-ruler').innerHTML = html;

  ITEM_EL.forEach((node) => layoutItem(node));

  const end = projectEnd();
  $('endmark').classList.toggle('hidden', end <= 0);
  $('endmark').style.left = `calc(var(--head-w) + ${(end * PPS).toFixed(1)}px)`;
  refreshPlayhead(POSITION);
}

function refreshPlayhead(at) {
  $('playhead').style.left = `calc(var(--head-w) + ${(at * PPS).toFixed(1)}px)`;
}

/* =============================================================== interaction */

function paintSelection() {
  ITEM_EL.forEach((node) => node.classList.toggle('sel', !!(SEL && node._item === SEL.item)));
  const lanes = laneList();
  document.querySelectorAll('.tl-heads .head').forEach((head, index) => {
    head.classList.toggle('sel',
      !!(SEL && SEL.kind === 'track' && lanes[index] && lanes[index].track === SEL.track));
  });
}

function selectItem(lane, item) {
  SEL = {kind: lane.kind === 'audio' ? 'clip' : 'block', track: lane.track, item};
  paintSelection();
  renderInspector();
}

function selectTrack(track) {
  SEL = {kind: 'track', track};
  paintSelection();
  renderInspector();
}

function selectNothing() {
  SEL = null;
  paintSelection();
  renderInspector();
}

/**
 * How far a block may move without colliding.
 *
 * Neighbours are sorted into "left of me" and "right of me" by their midpoint
 * rather than by overlap, which stays meaningful while a block is dragged
 * through one. `refStart`/`refEnd` is the interval to judge against: the
 * position a drag started from, so a fast pointer cannot squeeze past a
 * neighbour -- or the freshly typed one when a number was entered by hand.
 */
function neighbourBounds(track, item, refStart, refEnd) {
  const centre = (refStart + refEnd) / 2;
  let before = 0;
  let after = Infinity;
  for (const other of track.blocks) {
    if (other === item) continue;
    const otherEnd = other.start_s + other.duration_s;
    if ((other.start_s + otherEnd) / 2 <= centre) before = Math.max(before, otherEnd);
    else after = Math.min(after, other.start_s);
  }
  return {before, after};
}

function clampBlock(track, block) {
  const bounds = neighbourBounds(track, block, block.start_s, block.start_s + block.duration_s);
  const room = Math.max(MIN_LENGTH, bounds.after - bounds.before);
  block.duration_s = round3(clamp(block.duration_s, MIN_LENGTH, room));
  block.start_s = round3(clamp(block.start_s, bounds.before,
                               Math.max(bounds.before, bounds.after - block.duration_s)));
  fitFades(block);
}

/** Keeps the fades inside their block; the bridge rejects anything else. */
function fitFades(item) {
  const total = item.fade_in_s + item.fade_out_s;
  if (total <= item.duration_s || total <= 0) return;
  const factor = item.duration_s / total;
  item.fade_in_s = round3(item.fade_in_s * factor);
  item.fade_out_s = round3(item.fade_out_s * factor);
}

function startDrag(event, node) {
  if (event.button !== 0) return;
  const lane = node._lane;
  const item = node._item;
  selectItem(lane, item);

  const mode = event.target.classList.contains('grip')
    ? (event.target.classList.contains('l') ? 'left' : 'right') : 'move';

  // Clips carry their length implicitly ("to the end of the file") until an
  // edge is dragged; make it explicit at that moment.
  if (lane.kind === 'audio' && item.duration_s <= 0)
    item.duration_s = round3(clipLength(lane.track, item));

  const bounds = lane.kind === 'audio' ? {before: 0, after: Infinity}
    : neighbourBounds(lane.track, item, item.start_s, item.start_s + item.duration_s);
  const origin = {start: item.start_s, length: item.duration_s, x: event.clientX};
  let moved = false;

  node.setPointerCapture(event.pointerId);
  event.preventDefault();

  const onMove = (move) => {
    const delta = (move.clientX - origin.x) / PPS;
    if (Math.abs(move.clientX - origin.x) > 2) moved = true;
    const free = move.altKey;

    if (mode === 'move') {
      let start = snapTime(origin.start + delta, free);
      start = clamp(start, bounds.before, Math.max(bounds.before, bounds.after - origin.length));
      item.start_s = round3(Math.max(0, start));
    } else if (mode === 'left') {
      const end = origin.start + origin.length;
      let start = snapTime(origin.start + delta, free);
      start = clamp(start, Math.max(0, bounds.before), end - MIN_LENGTH);
      item.start_s = round3(start);
      item.duration_s = round3(end - start);
    } else {
      let end = snapTime(origin.start + origin.length + delta, free);
      end = clamp(end, item.start_s + MIN_LENGTH, bounds.after);
      item.duration_s = round3(end - item.start_s);
    }
    layoutItem(node);
  };

  const finish = () => {
    node.onpointermove = node.onpointerup = node.onpointercancel = null;
    try { node.releasePointerCapture(event.pointerId); } catch { /* already gone */ }
    if (!moved) return;                       // a plain click only selects
    fitFades(item);
    if (lane.kind === 'light') lane.track.blocks.sort((a, b) => a.start_s - b.start_s);
    markDirty();
    layoutItem(node);
    layoutTimeline();
    renderInspector();
  };

  node.onpointermove = onMove;
  node.onpointerup = finish;
  // Without this a cancelled gesture leaves the block stuck to the pointer.
  node.onpointercancel = finish;
}

/* ---------------------------------------------------------------- audio drop */

function wireDrop(element, lane) {
  element.ondragover = (event) => { event.preventDefault(); element.classList.add('drop'); };
  element.ondragleave = (event) => {
    if (!element.contains(event.relatedTarget)) element.classList.remove('drop');
  };
  element.ondrop = (event) => {
    event.preventDefault();
    element.classList.remove('drop');
    const at = snapTime(timeAtClientX(event.clientX), event.altKey);
    for (const file of event.dataTransfer.files) uploadAudio(file, lane, at);
  };
}

/* Drag and drop was the only way in, and an empty lane gives no hint that it
 * is a drop target at all. A file picker is the discoverable path; the drop
 * handler stays for the quick way. */
function pickAudio(lane, at) {
  const input = $('file-audio');
  input.value = '';
  input._target = {lane, at};
  input.click();
}

$('file-audio').onchange = async (event) => {
  const target = $('file-audio')._target;
  if (!target) return;
  for (const file of event.target.files) await uploadAudio(file, target.lane, target.at);
  $('file-audio').value = '';
};

$('btn-add-music').onclick = () => {
  if (!PROJ) return toast('Erst ein Projekt öffnen.', 'err');
  let lane = laneList().find((entry) => entry.kind === 'audio');
  if (!lane) { addAudioTrack(); lane = laneList().find((entry) => entry.kind === 'audio'); }
  pickAudio(lane, snapTime(POSITION, false));
};

async function uploadAudio(file, lane, at) {
  const pending = toast(`${file.name} wird geladen …`, '', 0);
  const answer = await api('/api/audio/' + encodeURIComponent(file.name),
    {method: 'POST', body: await file.arrayBuffer()});
  pending.remove();
  if (!answer.ok) return toast(answer.error, 'err', 12000);

  lane.track.clips.push({
    file: answer.file, start_s: round3(at), offset_s: 0,
    duration_s: answer.duration_s, gain_db: 0, fade_in_s: 0, fade_out_s: 0,
  });
  markDirty();
  await saveProject(true);          // the bridge answers with the waveform
  toast(`${file.name} eingefügt.`, 'ok', 2500);
}

/* --------------------------------------------------------------- ruler scrub */

let scrubbing = false;

$('tl-ruler').onpointerdown = (event) => {
  scrubbing = true;
  $('tl-ruler').setPointerCapture(event.pointerId);
  FOLLOW = false;
  seekTo(timeAtClientX(event.clientX));
};
$('tl-ruler').onpointermove = (event) => { if (scrubbing) seekTo(timeAtClientX(event.clientX)); };
$('tl-ruler').onpointerup = $('tl-ruler').onpointercancel = () => {
  if (scrubbing) seekTo(POSITION, true);
  scrubbing = false;
  FOLLOW = true;
};

let seekPending = 0;
function seekTo(at, force = false) {
  POSITION = at;
  SEEK_HINT = {at, until: Date.now() + 700};
  refreshPlayhead(at);
  const now = Date.now();
  if (!force && now - seekPending < 60) return;   // the bridge is the clock
  seekPending = now;
  post('/api/transport', {action: 'seek', position: round3(at)});
}

/* ---------------------------------------------------------------------- zoom */

function setZoom(value, anchorSeconds) {
  const scroll = $('tl');
  const anchor = anchorSeconds !== undefined ? anchorSeconds
    : timeAtClientX(scroll.getBoundingClientRect().left + scroll.clientWidth / 2);
  PPS = clamp(Math.round(value), 2, 300);
  layoutTimeline();
  scroll.scrollLeft = anchor * PPS - scroll.clientWidth / 2;
}

$('btn-zoom-in').onclick = () => setZoom(PPS * 1.4);
$('btn-zoom-out').onclick = () => setZoom(PPS / 1.4);
$('btn-zoom-fit').onclick = () => {
  const span = Math.max(10, projectEnd() + 2);
  setZoom(($('tl').clientWidth - 190) / span, 0);
  $('tl').scrollLeft = 0;
};
$('btn-snap').onclick = () => {
  SNAP = !SNAP;
  $('btn-snap').setAttribute('aria-pressed', String(SNAP));
  // The grid lines are what the snapping snaps to, so hiding them is the
  // honest feedback -- a button that only changes an invisible variable reads
  // as broken.
  document.querySelectorAll('.lane').forEach((lane) => lane.classList.toggle('nogrid', !SNAP));
  layoutTimeline();
};

$('tl').addEventListener('wheel', (event) => {
  if (!event.ctrlKey) return;
  event.preventDefault();
  setZoom(PPS * (event.deltaY < 0 ? 1.15 : 1 / 1.15), timeAtClientX(event.clientX));
}, {passive: false});

/* ============================================================= adding things */

$('btn-add-block').onclick = () => addBlock();
$('btn-add-audio').onclick = () => addAudioTrack();
$('btn-add-light').onclick = () => addLightTrack();

function addBlock() {
  if (!PROJ) return toast('Erst ein Projekt öffnen.', 'err');
  if (!PROJ.light_tracks.length) return toast('Erst eine Lichtspur anlegen (+L).', 'err');

  const track = SEL && SEL.track && PROJ.light_tracks.includes(SEL.track)
    ? SEL.track : PROJ.light_tracks[0];

  const block = {
    start_s: snapTime(POSITION, false), duration_s: 4, cue: 1, hue: 0,
    brightness: 255, param: 128, fade_in_s: 0.5, fade_out_s: 0.5, label: '',
  };

  // Slide to the first gap that fits, so the project stays saveable.
  for (const other of [...track.blocks].sort((a, b) => a.start_s - b.start_s)) {
    const end = round3(other.start_s + other.duration_s);
    if (block.start_s < end && other.start_s < block.start_s + block.duration_s)
      block.start_s = end;
  }

  track.blocks.push(block);
  track.blocks.sort((a, b) => a.start_s - b.start_s);
  markDirty();
  buildTimeline();
  selectItem(laneOf(track), block);
}

function addAudioTrack() {
  if (!PROJ) return toast('Erst ein Projekt öffnen.', 'err');
  PROJ.audio_tracks.push({
    name: `Audio ${PROJ.audio_tracks.length + 1}`, gain_db: 0, mute: false, clips: [],
  });
  markDirty();
  buildTimeline();
  selectTrack(PROJ.audio_tracks[PROJ.audio_tracks.length - 1]);
}

function availableZones() {
  const out = [];
  for (const model of (STATE ? STATE.models : []))
    for (let zone = 0; zone < model.zones; zone++) out.push({model: model.name, zone});
  return out;
}

function addLightTrack() {
  if (!PROJ) return toast('Erst ein Projekt öffnen.', 'err');
  const taken = new Set(PROJ.light_tracks.map((track) => `${track.model}/${track.zone}`));
  const free = availableZones().find((entry) => !taken.has(`${entry.model}/${entry.zone}`));
  if (!free) return toast('Für jede Zone jedes Modells gibt es bereits eine Spur.', 'err');

  const zones = (STATE.models.find((model) => model.name === free.model) || {}).zones || 1;
  PROJ.light_tracks.push({
    model: free.model, zone: free.zone, blocks: [],
    name: zones === 1 ? free.model : `${free.model} Zone ${free.zone + 1}`,
  });
  markDirty();
  buildTimeline();
  selectTrack(PROJ.light_tracks[PROJ.light_tracks.length - 1]);
}

function deleteSelection() {
  if (!SEL || !PROJ) return;

  if (SEL.kind === 'track') {
    const list = PROJ.audio_tracks.includes(SEL.track) ? PROJ.audio_tracks : PROJ.light_tracks;
    const contents = list === PROJ.audio_tracks ? SEL.track.clips : SEL.track.blocks;
    if (contents.length &&
        !confirm(`Die Spur enthält ${contents.length} Element(e). Wirklich löschen?`)) return;
    list.splice(list.indexOf(SEL.track), 1);
  } else {
    const list = SEL.kind === 'clip' ? SEL.track.clips : SEL.track.blocks;
    const index = list.indexOf(SEL.item);
    if (index < 0) return;
    list.splice(index, 1);
  }

  SEL = null;
  markDirty();
  buildTimeline();
  renderInspector();
}

/* =================================================================== inspector */

function renderInspector() {
  dropPreviews($('insp-body'));
  const kind = $('insp-kind');
  const title = $('insp-title');
  const body = $('insp-body');

  if (!SEL || !PROJ) {
    kind.textContent = 'Auswahl';
    title.textContent = '—';
    body.innerHTML = `<div class="empty">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"
           stroke-linecap="round"><path d="M3 8h18M3 16h18"/><circle cx="9" cy="8" r="2.4"/>
        <circle cx="16" cy="16" r="2.4"/></svg>
      <div>Einen Block, einen Clip oder einen Spurkopf anklicken.</div></div>`;
    return;
  }

  if (SEL.kind === 'track') renderTrackInspector();
  else if (SEL.kind === 'clip') renderClipInspector();
  else renderBlockInspector();
}

/** One setter for every [data-key] control the inspector rendered. */
function wireInspector(apply) {
  const body = $('insp-body');
  body.querySelectorAll('[data-key]').forEach((input) => {
    const handler = () => {
      const value = input.type === 'number' || input.type === 'range' ? +input.value
        : input.type === 'checkbox' ? input.checked : input.value;
      // A slider and its number box are two views of one value; whichever was
      // touched updates the other.
      if (input.dataset.pair) {
        body.querySelectorAll(`[data-pair="${input.dataset.pair}"]`).forEach((twin) => {
          if (twin !== input) twin.value = value;
        });
      }
      apply(input.dataset.key, value, input);
    };
    const live = input.type === 'text' || input.type === 'number' || input.type === 'range';
    input.addEventListener(live ? 'input' : 'change', handler);
  });
}

const numberField = (label, value, key, step, min = 0, max = 100000) => `
  <div class="f"><label class="lbl">${label}</label>
    <input type="number" value="${value}" step="${step}" min="${min}" max="${max}"
           data-key="${key}" style="width:100%"></div>`;

/** The zone a light track drives, with the lamps hanging on it. */
function zoneOutputs(track) {
  const model = STATE && STATE.models.find((entry) => entry.name === track.model);
  if (!model || !model.outputs) return null;
  return model.outputs[track.zone] || null;
}

/** "flaeche_links + flaeche_rechts · 60 Pixel", or an honest blank. */
function describeOutputs(outputs) {
  if (!outputs || !outputs.strips.length) return 'keine Strips zugeordnet';
  return outputs.strips.map((strip) =>
    strip.name + (strip.reverse ? ' ↔' : '')).join(' + ') + ` · ${outputs.pixels} Pixel`;
}

/** A slider with a numeric field beside it, both editing the same value. */
const rangeField = (label, value, key, min, max, step, unit = '') => `
  <div class="f">
    <div class="valrow"><label class="lbl" style="margin:0">${label}</label>
      <span class="v"><input type="number" data-key="${key}" data-pair="${key}"
        value="${value}" min="${min}" max="${max}" step="${step}"
        style="width:74px;text-align:right">${unit ? ' ' + unit : ''}</span></div>
    <input type="range" class="slider" data-key="${key}" data-pair="${key}"
      min="${min}" max="${max}" step="${step}" value="${value}">
  </div>`;

const sliderField = (label, value, key, extra = '', shown = value) => `
  <div class="f">
    <div class="valrow"><label class="lbl" style="margin:0">${label}</label>
      <span class="v" data-show="${key}">${shown}</span></div>
    <input type="range" class="slider ${extra}" min="0" max="255" value="${value}" data-key="${key}">
  </div>`;

function renderBlockInspector() {
  const block = SEL.item;
  $('insp-kind').textContent = 'Effektblock';
  $('insp-title').textContent = SEL.track.name || SEL.track.model;

  const outputs = zoneOutputs(SEL.track);
  const pixels = outputs && outputs.pixels ? outputs.pixels : 34;

  $('insp-body').innerHTML = `
    <div class="strip-box lg"><canvas class="strip" id="insp-strip"></canvas></div>
    <p class="dim" style="font-size:11.5px;margin:6px 0 14px">
      läuft auf <b style="color:var(--text-2)">${esc(describeOutputs(outputs))}</b></p>

    <div id="relay-state"></div>

    <label class="lbl">Effekt</label>
    <div class="cues" id="cue-picker" style="margin-bottom:15px"></div>

    ${sliderField('Farbton', block.hue, 'hue', 'hue')}
    ${sliderField('Helligkeit', block.brightness, 'brightness', 'level',
      Math.round(block.brightness / 255 * 100) + ' %')}
    ${sliderField('Tempo', block.param, 'param', '',
      (periodMs(block.param) / 1000).toFixed(2) + ' s')}

    <div class="f"><label class="lbl">Beschriftung</label>
      <input type="text" data-key="label" value="${esc(block.label)}"
             placeholder="${esc(cueName(block.cue))}" style="width:100%"></div>

    <div class="fgrid">
      ${numberField('Start (s)', block.start_s, 'start_s', 0.05)}
      ${numberField('Länge (s)', block.duration_s, 'duration_s', 0.05, MIN_LENGTH)}
      ${numberField('Einblenden (s)', block.fade_in_s, 'fade_in_s', 0.1)}
      ${numberField('Ausblenden (s)', block.fade_out_s, 'fade_out_s', 0.1)}
    </div>

    <div class="row" style="margin-top:6px">
      <button class="danger" id="insp-del">Block löschen</button>
      <span class="dim" style="font-size:11.5px">Ende ${fmtTime(block.start_s + block.duration_s)}</span>
    </div>`;

  // The preview is as long as the real chain, so a chase looks like it will
  // look on the wing rather than on an arbitrary 34 pixel stand-in.
  preview($('insp-strip'), () => ({
    cue: block.cue, hue: block.hue, brightness: block.brightness, param: block.param,
    max: modelCeiling(SEL.track),
  }), pixels);

  buildCuePicker(block);
  renderRelayState(block, outputs, pixels);

  wireInspector((key, value) => {
    block[key] = value;
    if (key === 'start_s' || key === 'duration_s') {
      clampBlock(SEL.track, block);
      SEL.track.blocks.sort((a, b) => a.start_s - b.start_s);
    } else if (key === 'fade_in_s' || key === 'fade_out_s') {
      fitFades(block);
    }
    const shown = $('insp-body').querySelector(`[data-show="${key}"]`);
    if (shown) {
      shown.textContent = key === 'brightness' ? Math.round(value / 255 * 100) + ' %'
        : key === 'param' ? (periodMs(value) / 1000).toFixed(2) + ' s' : value;
    }
    markDirty();
    refreshItem(block);
    layoutTimeline();
    refreshRelayState();
  });
  $('insp-del').onclick = deleteSelection;
}

const modelCeiling = (track) => {
  const model = STATE && STATE.models.find((entry) => entry.name === track.model);
  return model ? (model.max_brightness ?? 255) : 255;
};

/**
 * What this block does to the relays of its zone.
 *
 * Relays are not automated on their own -- three of the four sources are read
 * straight out of the effect engine, which is what keeps them from costing an
 * RC channel each. Efficient, and completely invisible until it is shown.
 */
function refreshRelayState() {
  if (!SEL || SEL.kind !== 'block') return;
  const outputs = zoneOutputs(SEL.track);
  renderRelayState(SEL.item, outputs, outputs && outputs.pixels ? outputs.pixels : 34);
}

function renderRelayState(block, outputs, pixelCount) {
  const box = $('relay-state');
  if (!box) return;
  const relays = outputs ? outputs.relays : [];
  if (!relays.length) { box.innerHTML = ''; return; }

  // A strobe switches the relay on and off within one cycle, so a single
  // moment says little -- sample a whole period and report what happens.
  const period = periodMs(block.param);
  const show = {cue: block.cue, hue: block.hue, brightness: block.brightness,
                param: block.param};
  const states = relays.map(() => ({on: 0, off: 0}));
  for (let step = 0; step < 24; step++) {
    const frame = renderEffect(show, step * period / 24, pixelCount,
                               {max: modelCeiling(SEL.track)});
    relays.forEach((relay, index) => {
      if (relayWants(relay, show, frame)) states[index].on++;
      else states[index].off++;
    });
  }

  box.innerHTML = `<label class="lbl">Relais dieser Zone</label>
    <div class="relays">${relays.map((relay, index) => {
      const {on, off} = states[index];
      const mode = on && off ? 'blinkt' : on ? 'an' : 'aus';
      const slow = relay.min_on_ms || relay.min_off_ms;
      return `<div class="relay ${on && off ? 'pulse' : on ? 'on' : 'off'}">
        <i></i>
        <span class="rn">${esc(relay.name)}</span>
        <span class="rs">${mode}</span>
        <span class="rw">${esc(relayExplains(relay))}${
          slow ? ` · träge ${relay.min_on_ms}/${relay.min_off_ms} ms` : ''}</span>
      </div>`;
    }).join('')}</div>
    <p class="dim" style="font-size:11px;margin:6px 0 14px">Relais folgen dem Effekt,
      sie haben keine eigene Spur — das spart die RC-Kanäle. Die Quelle je Relais
      steht im Tab <b>Modelle</b>.</p>`;
}

/** The effect picker: every cue running its own animation, at a glance. */
function buildCuePicker(block) {
  const picker = $('cue-picker');
  picker.innerHTML = '';
  CUES.forEach((name, index) => {
    const tile = document.createElement('button');
    tile.className = 'cue';
    tile.setAttribute('aria-pressed', String(block.cue === index));
    tile.title = `${index}: ${name}`;

    const canvas = document.createElement('canvas');
    const caption = document.createElement('div');
    caption.className = 'n';
    caption.textContent = name;
    tile.append(canvas, caption);
    picker.append(tile);

    preview(canvas, () => ({
      cue: index, hue: block.hue, brightness: 255, param: block.param,
    }), 12);

    tile.onclick = () => {
      block.cue = index;
      markDirty();
      picker.querySelectorAll('.cue').forEach((other, i) =>
        other.setAttribute('aria-pressed', String(i === index)));
      const label = $('insp-body').querySelector('[data-key="label"]');
      if (label) label.placeholder = cueName(index);
      refreshItem(block);
      // The cue is what most relays follow, so their state changes with it.
      refreshRelayState();
    };
  });
}

function renderClipInspector() {
  const clip = SEL.item;
  $('insp-kind').textContent = 'Audioclip';
  $('insp-title').textContent = clip.file.replace(/^audio\//, '');
  const length = clipLength(SEL.track, clip);
  const span = Math.max(30, Math.ceil(projectEnd() + 10));

  $('insp-body').innerHTML = `
    ${rangeField('Start auf der Zeitachse', clip.start_s, 'start_s', 0, span, 0.01, 's')}
    ${rangeField('Länge', clip.duration_s, 'duration_s', 0, Math.max(1, Math.ceil(length + 30)), 0.01, 's')}
    ${rangeField('Anfang in der Datei', clip.offset_s, 'offset_s', 0, Math.max(1, Math.ceil(length + clip.offset_s)), 0.01, 's')}
    ${rangeField('Lautstärke', clip.gain_db, 'gain_db', -60, 12, 0.5, 'dB')}
    ${rangeField('Einblenden', clip.fade_in_s, 'fade_in_s', 0, Math.max(1, Math.ceil(length)), 0.1, 's')}
    ${rangeField('Ausblenden', clip.fade_out_s, 'fade_out_s', 0, Math.max(1, Math.ceil(length)), 0.1, 's')}
    <p class="dim" style="font-size:11.5px">Länge 0 heißt „bis zum Ende der Datei“ —
      gerade sind das ${fmtTime(length)}. Die Wellenform wird beim Speichern neu gerechnet.</p>
    <div class="row"><button class="danger" id="insp-del">Clip entfernen</button></div>`;

  wireInspector((key, value) => {
    clip[key] = value;
    markDirty();
    refreshItem(clip);
    layoutTimeline();
  });
  $('insp-del').onclick = deleteSelection;
}

function renderTrackInspector() {
  const track = SEL.track;
  const isAudio = PROJ.audio_tracks.includes(track);
  $('insp-kind').textContent = isAudio ? 'Audiospur' : 'Lichtspur';
  $('insp-title').textContent = track.name || track.model || '—';

  if (isAudio) {
    $('insp-body').innerHTML = `
      <div class="f"><label class="lbl">Name</label>
        <input type="text" data-key="name" value="${esc(track.name)}" style="width:100%"></div>
      ${rangeField('Lautstärke', track.gain_db, 'gain_db', -60, 12, 0.5, 'dB')}
      <div class="f"><label class="lbl">Stumm</label>
        <input type="checkbox" data-key="mute" ${track.mute ? 'checked' : ''}></div>
      <div class="row"><button class="danger" id="insp-del">Spur löschen</button>
        <span class="dim" style="font-size:11.5px">${track.clips.length} Clip(s)</span></div>`;
  } else {
    const models = STATE ? STATE.models : [];
    const model = models.find((entry) => entry.name === track.model);
    const zones = model ? model.zones : 1;
    $('insp-body').innerHTML = `
      <div class="f"><label class="lbl">Name</label>
        <input type="text" data-key="name" value="${esc(track.name)}"
               placeholder="${esc(track.model)}" style="width:100%"></div>
      <div class="f"><label class="lbl">Modell</label>
        <select data-key="model" style="width:100%">${models.map((entry) =>
          `<option value="${esc(entry.name)}" ${entry.name === track.model ? 'selected' : ''}>${esc(entry.name)} — Sender ${entry.tx_port + 1}</option>`
        ).join('') || `<option>${esc(track.model)}</option>`}</select></div>
      ${zones > 1 ? `<div class="f"><label class="lbl">Zone</label>
        <select data-key="zone" style="width:100%">${Array.from({length: zones}, (_, zone) =>
          `<option value="${zone}" ${track.zone === zone ? 'selected' : ''}>Zone ${zone + 1}</option>`
        ).join('')}</select></div>` : ''}
      <div class="f"><label class="lbl">Steuert</label>
        <div class="note" style="margin:0">${esc(describeOutputs(zoneOutputs(track)))}${
          (() => { const o = zoneOutputs(track);
            return o && o.relays.length
              ? '<br>' + o.relays.map((r) => esc(r.name) + ' — ' + esc(relayExplains(r))).join('<br>')
              : ''; })()}</div></div>
      ${model ? '' : `<div class="note err">Das Modell „${esc(track.model)}“ steht nicht in
        der Show-Konfiguration — diese Spur steuert nichts.</div>`}
      <div class="row"><button class="danger" id="insp-del">Spur löschen</button>
        <span class="dim" style="font-size:11.5px">${track.blocks.length} Block/Blöcke</span></div>`;
  }

  wireInspector((key, value) => {
    track[key] = key === 'zone' ? +value : value;
    markDirty();
    // Model and zone change what the track drives, so the lanes are rebuilt.
    // Name, gain and mute only relabel the head -- redrawing everything there
    // would tear the field out from under the cursor mid-word.
    if (key === 'model' || key === 'zone') { buildTimeline(); renderInspector(); }
    else refreshHead(track);
  });
  $('insp-del').onclick = deleteSelection;
}

/* =================================================================== transport */

$('btn-play').onclick = async () => {
  FOLLOW = true;
  const answer = await post('/api/transport', {action: 'play'});
  if (!answer.ok) toast(answer.error, 'err');
};
$('btn-pause').onclick = () => post('/api/transport', {action: 'pause'});
$('btn-stop').onclick = () => {
  FOLLOW = true;
  SEEK_HINT = {at: 0, until: Date.now() + 700};
  post('/api/transport', {action: 'stop'});
};

function followPlayhead(at) {
  if (!FOLLOW || VIEW !== 'show') return;
  const scroll = $('tl');
  const x = at * PPS;
  const left = scroll.scrollLeft;
  if (x < left + 40 || x > left + scroll.clientWidth - 240)
    scroll.scrollLeft = Math.max(0, x - scroll.clientWidth * 0.3);
}

function renderTransport(transport) {
  if (!transport) {
    ['btn-play', 'btn-pause', 'btn-stop'].forEach((id) => $(id).disabled = true);
    $('tnote').textContent = 'kein Projekt-Transport';
    return;
  }

  const hint = SEEK_HINT && Date.now() < SEEK_HINT.until ? SEEK_HINT.at : null;
  const at = hint !== null && !transport.playing ? hint : transport.position;
  if (transport.playing) SEEK_HINT = null;

  POSITION = at;
  $('clock').textContent = fmtTime(at);
  $('clock-total').textContent = 'von ' + fmtTime(transport.duration);
  refreshPlayhead(at);
  if (transport.playing) followPlayhead(at);

  // Nothing on any track means the show is zero seconds long, and the bridge
  // stops the moment it starts. Saying so beats a button that does nothing.
  const empty = transport.project && transport.duration <= 0;
  $('btn-play').disabled = transport.playing || !transport.project || empty;
  $('btn-pause').disabled = !transport.playing;
  $('btn-stop').disabled = !transport.project;

  const tnote = $('tnote');
  tnote.classList.remove('live');
  if (!transport.project) tnote.textContent = 'kein Projekt geöffnet';
  else if (empty) tnote.textContent = 'leer — erst Musik oder einen Effekt einfügen';
  else if (transport.playing && transport.source === 'timeline') {
    tnote.textContent = 'Show läuft'; tnote.classList.add('live');
  } else if (!transport.device && transport.device_error) {
    tnote.textContent = 'kein Audiogerät — Uhr läuft trotzdem';
  } else tnote.textContent = 'bereit';
}

/* ======================================================================= Bühne */

/* Groups a model's channels into zones of four, so a two zone aircraft shows
 * two strips. The roles arrive in the order the configuration lists them. */
function zonesOf(model) {
  const out = [];
  for (let start = 0; start + 4 <= model.channels.length; start += 4) {
    const four = model.channels.slice(start, start + 4);
    const by = (role) => four.find((channel) => channel.role === role);
    out.push({
      index: out.length,
      cue: by('cue'), hue: by('hue'),
      brightness: by('brightness'), param: by('param'),
      channels: four,
      live: four.some((channel) => channel.live),
    });
  }
  return out;
}

const zoneShow = (zone) => ({
  cue: zone.cue ? (zone.cue.step ?? 0) : 0,
  hue: zone.hue ? zone.hue.level : 0,
  brightness: zone.brightness ? zone.brightness.level : 0,
  param: zone.param ? zone.param.level : 128,
});

let stageSignature = '';

function renderStage(state) {
  const signature = state.models.map((model) =>
    `${model.name}:${model.channels.length}:${model.tx_port}`).join('|');

  if (signature !== stageSignature) {
    stageSignature = signature;
    dropPreviews($('stage'));
    $('stage').innerHTML = '';

    for (const model of state.models) {
      for (const zone of zonesOf(model)) {
        const card = document.createElement('div');
        card.className = 'plane';
        card.dataset.plane = `${model.name}/${zone.index}`;
        card.innerHTML = `
          <div class="top">
            <span class="name">${esc(model.name)}</span>
            ${zonesOf(model).length > 1 ? `<span class="tag">Zone ${zone.index + 1}</span>` : ''}
            <span class="grow"></span>
            <span class="tag">Sender ${model.tx_port + 1}</span>
            <span class="tag">Kanal ${zone.channels[0].channel}–${zone.channels[3].channel}</span>
          </div>
          <div class="strip-box"><canvas class="strip"></canvas></div>
          <div class="cuename"><span class="swatch"></span><span class="cn">—</span></div>
          <div class="meters">
            <div class="meter hue"><span class="k">Farbton</span>
              <span class="t hue"><i></i></span><span class="v"></span></div>
            <div class="meter bri"><span class="k">Helligkeit</span>
              <span class="t"><i></i></span><span class="v"></span></div>
            <div class="meter par"><span class="k">Tempo</span>
              <span class="t"><i></i></span><span class="v"></span></div>
          </div>
          <details class="raw"><summary>Rohwerte</summary>
            <div class="tablewrap"><table>
              <thead><tr><th>Kanal</th><th>Rolle</th><th>CC</th><th class="n">µs</th><th>Wert</th></tr></thead>
              <tbody></tbody></table></div>
          </details>`;
        $('stage').append(card);

        // The card keeps rendering from whatever the newest frame says.
        card._zone = zone;
        card._max = model.max_brightness ?? 255;
        preview(card.querySelector('canvas'), () => {
          const current = card._zone;
          if (!current) return null;
          if (!current.live) return {failsafe: true, max: card._max};
          return {...zoneShow(current), max: card._max};
        }, 30);
      }
    }
  }

  for (const model of state.models) {
    for (const zone of zonesOf(model)) {
      const card = $('stage').querySelector(
        `[data-plane="${CSS.escape(model.name + '/' + zone.index)}"]`);
      if (!card) continue;
      card._zone = zone;
      card._max = model.max_brightness ?? 255;
      updatePlaneCard(card, zone);
    }
  }
}

function updatePlaneCard(card, zone) {
  const show = zoneShow(zone);
  // Without a link the aircraft shows amber, whatever the stale hue channel
  // still says -- the swatch has to agree with the strip above it.
  const [r, g, b] = zone.live ? hsv(show.hue, 255) : [255, 120, 0];

  card.classList.toggle('offline', !zone.live);
  card.querySelector('.cn').textContent = zone.live
    ? (show.cue ? cueName(show.cue) : 'aus') : 'Failsafe — kein Signal';
  const swatch = card.querySelector('.swatch');
  swatch.style.background = `rgb(${r},${g},${b})`;
  swatch.style.color = `rgb(${r},${g},${b})`;

  const meter = (name, fraction, text, hue) => {
    const box = card.querySelector('.meter.' + name);
    box.classList.toggle('off', !zone.live);
    box.querySelector('i').style.width = (clamp(fraction, 0, 1) * 100).toFixed(1) + '%';
    box.querySelector('.v').textContent = text;
    if (hue) box.querySelector('.t').style.setProperty('--hue', hue);
  };
  meter('hue', show.hue / 255, String(show.hue), `rgb(${r},${g},${b})`);
  meter('bri', show.brightness / 255, Math.round(show.brightness / 255 * 100) + ' %');
  meter('par', show.param / 255, (periodMs(show.param) / 1000).toFixed(2) + ' s');

  card.querySelector('tbody').innerHTML = zone.channels.map((channel) => `
    <tr><td class="n">${channel.channel}</td><td>${esc(channel.role)}</td>
      <td>${channel.cc}${channel.cc_lsb !== null ? '+' + channel.cc_lsb : ''}</td>
      <td class="n">${channel.us}</td>
      <td class="${channel.live ? '' : 'dim'}">${channel.live ? esc(channel.decoded) : 'Failsafe'}</td>
    </tr>`).join('');
}

function renderConnections(state) {
  const midi = state.midi;
  const pico = state.pico;
  const rows = [
    ['MIDI-Port', `<code>${esc(midi.port)}</code>`, midi.connections.length
      ? midi.connections.map(esc).join('<br>')
      : '<span class="dim">niemand verbunden — in der DAW den Track-Ausgang hierher legen</span>'],
    ['MIDI-Nachrichten', midi.messages, midi.receiving
      ? `${midi.rate.toFixed(1)} pro Sekunde` : '<span class="dim">still</span>'],
    ['Bodenstation', `<code>${esc(pico.device)}</code>`, pico.dry_run
      ? 'dry-run — es wird kein Gerät geöffnet'
      : (pico.connected ? `${pico.frames} Frames gesendet`
        : `<span class="dim">${esc(pico.error || 'nicht verbunden')}</span>`)],
  ];
  if (pico.status.length)
    rows.push(['Firmware meldet', '',
      `<pre class="code" style="max-height:110px">${pico.status.map(esc).join('\n')}</pre>`]);

  $('conn').innerHTML = rows.map((row) =>
    `<tr><th style="width:170px">${row[0]}</th><td style="width:200px">${row[1]}</td><td>${row[2]}</td></tr>`
  ).join('');
}

/* ====================================================================== status */

function renderStatus(state) {
  const first = STATE === null;
  const previousModels = STATE
    ? STATE.models.map((model) => `${model.name}:${model.tx_port}`).join(',') : '';
  STATE = state;
  $('offline').classList.add('hidden');

  const midi = state.midi;
  const connected = midi.connections.length > 0;
  $('led-midi').className = 'led ' + (midi.receiving ? 'beat' : (connected ? 'warn' : 'bad'));
  $('txt-midi').textContent = midi.receiving
    ? `DAW ${midi.rate.toFixed(0)}/s`
    : (connected ? 'DAW verbunden' : 'DAW getrennt');

  const pico = state.pico;
  $('led-pico').className = 'led ' + (pico.dry_run ? 'warn' : (pico.connected ? 'ok' : 'bad'));
  $('txt-pico').textContent = pico.dry_run ? 'Bodenstation dry-run'
    : (pico.connected ? 'Bodenstation' : 'Bodenstation getrennt');

  $('txt-rate').textContent = `${state.rate_hz} Hz`;
  $('btn-blackout').setAttribute('aria-pressed', String(state.blackout));
  $('txt-blackout').textContent = state.blackout ? 'Blackout aktiv' : 'Blackout';

  renderTransport(state.transport);
  if (VIEW === 'stage') { renderStage(state); renderConnections(state); }
  if (LOCKED !== state.locked) { LOCKED = state.locked; applyLock(); }

  const models = state.models.map((model) => `${model.name}:${model.tx_port}`).join(',');
  if (models !== previousModels) {
    fillWiringModels();
    if (VIEW === 'wiring') loadWiring();
    if (PROJ) buildTimeline();          // the heads name the transmitter
  }
  if (first) {
    $('offline-host').textContent = location.host;
    if (!PROJ) buildTimeline();
  }
}

function applyLock() {
  const box = $('lock-note');
  box.classList.toggle('hidden', !LOCKED);
  box.textContent = 'Es läuft eine Show — es kommt MIDI herein oder der Transport spielt. '
    + 'Die Bearbeitung ist gesperrt, damit sich die Zuordnung nicht mitten in der Show verschiebt.';
  $('models').querySelectorAll('input, select, button')
    .forEach((element) => element.disabled = LOCKED);
  $('btn-config-save').disabled = LOCKED;
}

/* =============================================================== models view */

const RELAY_SOURCES = [
  ['pixel', 'folgt Pixel'], ['brightness', 'Master-Dimmer'],
  ['cue', 'ab Cue'], ['channel', 'eigener RC-Kanal'],
];

/* "Directly over the bus" is only offered where a slot exists for it -- an
 * option that cannot be saved is worse than one that is missing. */
const sourcesFor = (model) =>
  (model.bus && model.bus.enabled && (model.bus.relays || []).length)
    ? RELAY_SOURCES.concat([['bus', 'direkt über den Bus']])
    : RELAY_SOURCES;

/* Zone/relay combinations per transmitter, from /api/bus. The rules live on
 * the server; this is only the last answer it gave. */
let BUS = null;

/* The combinations as a matrix: zones down, bus relays across.
 *
 * As a flat list of tiles this is over a hundred buttons and reads as a wall.
 * Laid out on its two axes the shape of the trade-off is visible at a glance --
 * going down costs latency, going right costs payload bits, and the empty
 * bottom right corner is where the two run out together.
 *
 * `attrs(zones, relays)` supplies whatever the caller needs to catch the click.
 */
function busMatrix(combinations, chosenZones, chosenRelays, attrs) {
  const byZone = new Map();
  let widest = 0;
  for (const entry of combinations) {
    if (!byZone.has(entry.zones)) byZone.set(entry.zones, new Map());
    byZone.get(entry.zones).set(entry.relays, entry);
    widest = Math.max(widest, entry.relays);
  }
  const columns = Array.from({length: widest + 1}, (_, index) => index);

  const head = columns.map((relays) =>
    `<th>${relays === 0 ? 'keine' : relays}</th>`).join('');

  const rows = [...byZone.keys()].sort((a, b) => a - b).map((zones) => {
    const cells = columns.map((relays) => {
      const entry = byZone.get(zones).get(relays);
      if (!entry) return '<td class="bus-cell none" title="passt nicht ins Bitbudget">—</td>';
      const chosen = zones === chosenZones && relays === chosenRelays;
      return `<td class="bus-cell ${chosen ? 'on' : ''} ${entry.within_budget ? '' : 'slow'}"
        ${attrs(zones, relays)} title="${entry.spare_bits} Bit übrig">
        ${entry.latency_ms.toFixed(0)}</td>`;
    }).join('');
    return `<tr><th class="bus-zone">${zones}</th>${cells}</tr>`;
  }).join('');

  return `<div class="tablewrap"><table class="bus-matrix">
    <thead><tr><th class="bus-corner">Zonen \\ Relais</th>${head}</tr></thead>
    <tbody>${rows}</tbody>
  </table></div>
  <p class="dim" style="font-size:11.5px;margin:6px 0 0">
    Zahlen sind Millisekunden, bis dieselbe Zone wieder an der Reihe ist.
    — heißt: passt nicht ins Bitbudget.</p>`;
}

async function loadBus() {
  BUS = await api('/api/bus');
  // The answer usually arrives after the first render, and the models view is
  // often not the one on screen yet -- draw it in either case, or the chooser
  // silently stays empty until something else happens to redraw.
  if (CONFIG) renderModels();
}

/* Picking a combination rewrites the model: zones are groups of four channels,
 * bus relays are entries with a control change each. Existing zones keep their
 * control changes so a change of mind does not renumber a whole show. */
function applyBusChoice(model, zones, relays) {
  const groups = Math.max(1, Math.floor(model.channels.length / 4));
  const taken = new Set();
  if (CONFIG.blackout_cc !== null) taken.add(CONFIG.blackout_cc);
  for (const other of CONFIG.models) {
    if (other.midi_channel !== model.midi_channel || other === model) continue;
    other.channels.forEach((channel) => {
      taken.add(channel.cc);
      if (channel.cc_lsb != null) taken.add(channel.cc_lsb);
    });
    ((other.bus && other.bus.relays) || []).forEach((relay) => taken.add(relay.cc));
  }
  model.channels.forEach((channel) => {
    taken.add(channel.cc);
    if (channel.cc_lsb != null) taken.add(channel.cc_lsb);
  });

  const nextCC = () => {
    for (let cc = 20; cc <= 110; cc++) if (!taken.has(cc)) { taken.add(cc); return cc; }
    return 20;
  };

  if (zones > groups) {
    for (let zone = groups; zone < zones; zone++) {
      model.channels.push({role: 'cue', cc: nextCC(), quantize: 32, failsafe: 1000});
      model.channels.push({role: 'hue', cc: nextCC(), failsafe: 1500});
      model.channels.push({role: 'brightness', cc: nextCC(), cc_lsb: nextCC(),
                           failsafe: 1000});
      model.channels.push({role: 'param', cc: nextCC(), failsafe: 1500});
    }
  } else if (zones < groups) {
    model.channels.length = zones * 4;
    // Strips and relays must not be left pointing at a zone that is gone.
    if (model.plane) {
      model.plane.strips.forEach((s) => { s.zone = Math.min(s.zone, zones - 1); });
      model.plane.relays.forEach((r) => { r.zone = Math.min(r.zone, zones - 1); });
    }
  }

  const existing = (model.bus && model.bus.relays) || [];
  const list = existing.slice(0, relays);
  while (list.length < relays)
    list.push({name: `bus${list.length}`, cc: nextCC(), failsafe: false});
  model.bus = {enabled: true, relays: list};

  // A relay pointing at a slot that no longer exists would fail validation on
  // save; move it back to something that always works.
  if (model.plane) {
    model.plane.relays.forEach((relay) => {
      if (relay.source === 'bus' && relay.arg >= relays) {
        relay.source = 'cue';
        relay.arg = 1;
      }
    });
  }
}

/* The combination chooser for a model that already exists. Same table the
 * wizard shows, so both say the same thing about the same aircraft. */
function busPanel(model, mi) {
  if (!BUS || !BUS.ports) return '';
  const port = BUS.ports[String(model.tx_port)];
  if (!port) return '';

  const zones = Math.max(1, Math.floor(model.channels.length / 4));
  const relays = (model.bus && model.bus.relays ? model.bus.relays.length : 0);
  const on = !!(model.bus && model.bus.enabled);
  const free = (CONFIG.tx_ports.find((p) => p.id === model.tx_port) || {}).nchan
    - model.tx_offset;
  const classic = zones * 4 <= free;

  const matrix = busMatrix(port.combinations, on ? zones : -1, on ? relays : -1,
    (z, r) => `data-act="bus-pick" data-m="${mi}" data-zones="${z}" data-relays="${r}"`);

  return `
    <h3 class="section">Bus-Modus</h3>
    <p class="muted" style="margin:0 0 10px;font-size:12.5px">
      Ohne Bus trägt jede Zone vier eigene Kanäle — schnellstmöglich, aber
      ${Math.floor(free / 4)} Zone(n) sind das Maximum bei ${free} freien Kanälen.
      Mit Bus tragen acht Kanäle einen codierten Rahmen und die Zonen kommen reihum
      dran: mehr Zonen und direkt schaltbare Relais, dafür Wartezeit.
      Blass heißt langsamer als die Grenze von ${BUS.limit_ms} ms.
    </p>
    <label class="row" style="gap:8px;margin-bottom:10px">
      <input type="checkbox" ${on ? 'checked' : ''} data-act="bus-toggle" data-m="${mi}"
        ${classic || on ? '' : 'disabled'}>
      <span>Bus-Modus für dieses Modell${classic ? '' :
        ' — bei so vielen Zonen ohne Alternative'}</span>
    </label>
    ${matrix}`;
}

/* id 0 sits on GPIO2, id 1 on GPIO3 and so on -- see hardware/README.md. */
const portGpio = (id) => 2 + id;

async function loadConfig() {
  const answer = await api('/api/config');
  if (!answer.config) return toast(answer.error || 'Konfiguration nicht lesbar', 'err');
  CONFIG = answer.config;
  $('config-path').textContent = answer.path;
  renderModels();
  loadBus();          // fills in the combination tables once they arrive
}

function pinUsers(plane) {
  const users = new Map([[0, ['Debug-UART TX']], [1, ['Debug-UART RX']]]);
  const add = (pin, what) => {
    if (!users.has(pin)) users.set(pin, []);
    users.get(pin).push(what);
  };
  add(plane.sbus_pin, 'SBUS');
  (plane.pwm_pins || []).forEach((pin, index) => add(pin, `PWM ${index + 1}`));
  plane.strips.forEach((strip) => add(strip.pin, `Strip „${strip.name}“`));
  plane.relays.forEach((relay) => add(relay.pin, `Relais „${relay.name}“`));
  return users;
}

function renderModels() {
  const scroll = $('view-models').scrollTop;

  // One model, one receiver, one transmitter. Two models on the same jack is
  // almost always a mistake, so it is called out rather than silently allowed.
  const perPort = new Map();
  CONFIG.models.forEach((model) => {
    if (!perPort.has(model.tx_port)) perPort.set(model.tx_port, []);
    perPort.get(model.tx_port).push(model.name);
  });
  const shared = [...perPort.entries()].filter(([, names]) => names.length > 1);

  const warning = shared.length ? `<div class="note warn">
    ${shared.map(([port, names]) => `Sender-Buchse ${port + 1} ist mit
      <b>${names.map(esc).join('</b> und <b>')}</b> doppelt belegt.`).join('<br>')}
    Jedes Modell hat einen eigenen Empfänger und braucht deshalb eine eigene
    Buchse — es sei denn, beide Empfänger sind bewusst auf dasselbe Sendermodell
    gebunden.</div>` : '';

  $('models').innerHTML = warning + CONFIG.models.map((model, mi) => {
    const plane = model.plane;
    const zones = Math.max(1, Math.floor(model.channels.length / 4));

    const head = `<div class="card-head">
        <h2>${esc(model.name)}</h2>
        <span class="tag" style="font-size:11px;color:var(--text-3);border:1px solid var(--line);border-radius:999px;padding:2px 8px">
          Sender-Buchse ${model.tx_port + 1} · GP${portGpio(model.tx_port)}</span>
        <span class="grow"></span>
        <span class="dim" style="font-size:11.5px">MIDI-Kanal ${model.midi_channel} ·
          ${zones} Zone(n) · Kanal ${model.tx_offset + 1}–${model.tx_offset + model.channels.length}</span>
      </div>`;

    if (!plane) {
      return `<div class="card" style="margin-bottom:14px">${head}<div class="card-body">
        <p class="muted" style="margin:0 0 12px">Noch keine Bordkonfiguration — dieses
          Modell bekommt keine eigene Firmware.</p>
        <button data-act="add-plane" data-m="${mi}">Bordkonfiguration anlegen</button>
      </div></div>`;
    }

    const users = pinUsers(plane);
    const clash = (pin) => (users.get(pin) || []).length > 1;
    const why = (pin) => clash(pin) ? `GPIO ${pin} doppelt: ${users.get(pin).join(', ')}` : '';

    return `<div class="card" style="margin-bottom:14px">${head}<div class="card-body">

      <h3 class="section">Anbindung</h3>
      <div class="fgrid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
        <div><label class="lbl">Sender-Buchse</label>
          <select data-set="model" data-m="${mi}" data-key="tx_port" style="width:100%">
            ${Array.from({length: 8}, (_, port) =>
              `<option value="${port}" ${model.tx_port === port ? 'selected' : ''}>Buchse ${port + 1} · GP${portGpio(port)}</option>`).join('')}
          </select></div>
        <div><label class="lbl">MIDI-Kanal</label>
          <input type="number" min="1" max="16" value="${model.midi_channel}"
            data-set="model" data-m="${mi}" data-key="midi_channel" style="width:100%"></div>
        <div><label class="lbl">erster Kanal</label>
          <input type="number" min="0" max="15" value="${model.tx_offset}"
            data-set="model" data-m="${mi}" data-key="tx_offset" style="width:100%"></div>
        <div><label class="lbl">SBUS-GPIO</label>
          <input type="number" min="0" max="28" value="${plane.sbus_pin}"
            data-set="plane" data-m="${mi}" data-key="sbus_pin" style="width:100%"></div>
        <div><label class="lbl">Helligkeitsdeckel</label>
          <input type="number" min="1" max="255" value="${plane.max_brightness}"
            data-set="plane" data-m="${mi}" data-key="max_brightness" style="width:100%"></div>
        <div><label class="lbl">Renderrate (Hz)</label>
          <input type="number" min="30" max="1000" value="${plane.render_hz}"
            data-set="plane" data-m="${mi}" data-key="render_hz" style="width:100%"></div>
      </div>

      ${busPanel(model, mi)}

      <h3 class="section">LED-Strips · ${plane.strips.length}/8</h3>
      <div class="tablewrap"><table class="form">
        <thead><tr><th>Name</th><th>GPIO</th><th>Pixel</th><th>Zone</th>
          <th>Offset</th><th>rückwärts</th><th></th><th class="fill"></th></tr></thead>
        <tbody>${plane.strips.map((strip, si) => `
          <tr class="${clash(strip.pin) ? 'clash' : ''}" title="${esc(why(strip.pin))}">
            <td><input type="text" value="${esc(strip.name)}" style="width:130px"
              data-set="strips" data-m="${mi}" data-i="${si}" data-key="name"></td>
            <td><input type="number" min="0" max="28" value="${strip.pin}" style="width:66px"
              class="${clash(strip.pin) ? 'err' : ''}"
              data-set="strips" data-m="${mi}" data-i="${si}" data-key="pin"></td>
            <td><input type="number" min="1" max="256" value="${strip.count}" style="width:72px"
              data-set="strips" data-m="${mi}" data-i="${si}" data-key="count"></td>
            <td>${zoneSelect(zones, strip.zone, 'strips', mi, si)}</td>
            <td><input type="number" min="0" max="255" value="${strip.offset}" style="width:72px"
              data-set="strips" data-m="${mi}" data-i="${si}" data-key="offset"></td>
            <td><input type="checkbox" ${strip.reverse ? 'checked' : ''}
              data-set="strips" data-m="${mi}" data-i="${si}" data-key="reverse"></td>
            <td><button class="tiny danger" data-act="del" data-list="strips"
              data-m="${mi}" data-i="${si}" title="Entfernen">−</button></td>
            <td class="fill"></td>
          </tr>`).join('')}</tbody>
      </table></div>
      <div class="row" style="margin-top:10px">
        <button data-act="add-strip" data-m="${mi}">Strip hinzufügen</button>
        <span class="dim" style="font-size:11.5px">Gleicher Offset spiegelt zwei Strips,
          fortlaufende Offsets ergeben eine Kette für Lauflichter.</span>
      </div>

      <h3 class="section">Relais · ${plane.relays.length}/8</h3>
      <div class="tablewrap"><table class="form">
        <thead><tr><th>Name</th><th>GPIO</th><th>Zone</th><th>Quelle</th><th>Arg</th>
          <th>Schwelle</th><th>act.&nbsp;low</th><th>min&nbsp;an</th>
          <th>min&nbsp;aus</th><th></th><th class="fill"></th></tr></thead>
        <tbody>${plane.relays.map((relay, ri) => `
          <tr class="${clash(relay.pin) ? 'clash' : ''}" title="${esc(why(relay.pin))}">
            <td><input type="text" value="${esc(relay.name)}" style="width:118px"
              data-set="relays" data-m="${mi}" data-i="${ri}" data-key="name"></td>
            <td><input type="number" min="0" max="28" value="${relay.pin}" style="width:66px"
              class="${clash(relay.pin) ? 'err' : ''}"
              data-set="relays" data-m="${mi}" data-i="${ri}" data-key="pin"></td>
            <td>${zoneSelect(zones, relay.zone, 'relays', mi, ri)}</td>
            <td><select data-set="relays" data-m="${mi}" data-i="${ri}" data-key="source">
              ${sourcesFor(model).map(([value, label]) =>
                `<option value="${value}" ${relay.source === value ? 'selected' : ''}>${label}</option>`).join('')}
            </select></td>
            <td><input type="number" min="0" max="255" value="${relay.arg}" style="width:66px"
              data-set="relays" data-m="${mi}" data-i="${ri}" data-key="arg"></td>
            <td><input type="number" min="0" max="255" value="${relay.threshold}" style="width:72px"
              data-set="relays" data-m="${mi}" data-i="${ri}" data-key="threshold"></td>
            <td><input type="checkbox" ${relay.active_low ? 'checked' : ''}
              data-set="relays" data-m="${mi}" data-i="${ri}" data-key="active_low"></td>
            <td><input type="number" min="0" max="5000" value="${relay.min_on_ms}" style="width:76px"
              data-set="relays" data-m="${mi}" data-i="${ri}" data-key="min_on_ms"></td>
            <td><input type="number" min="0" max="5000" value="${relay.min_off_ms}" style="width:76px"
              data-set="relays" data-m="${mi}" data-i="${ri}" data-key="min_off_ms"></td>
            <td><button class="tiny danger" data-act="del" data-list="relays"
              data-m="${mi}" data-i="${ri}" title="Entfernen">−</button></td>
            <td class="fill"></td>
          </tr>`).join('')}</tbody>
      </table></div>
      <div class="row" style="margin-top:10px">
        <button data-act="add-relay" data-m="${mi}">Relais hinzufügen</button>
        <span class="dim" style="font-size:11.5px">min an/aus auf 0 für MOSFETs, ~200 ms für
          mechanische Relais. „active low“ für die üblichen Relaismodule.</span>
      </div>

      <h3 class="section">Positionslichter · ${plane.nav_lights.length}</h3>
      <div class="tablewrap"><table class="form">
        <thead><tr><th>Strip</th><th>Pixel</th><th>Farbe</th><th></th><th class="fill"></th></tr></thead>
        <tbody>${plane.nav_lights.map((nav, ni) => `
          <tr>
            <td><select data-set="nav_lights" data-m="${mi}" data-i="${ni}" data-key="strip">
              ${plane.strips.map((strip, si) =>
                `<option value="${si}" ${nav.strip === si ? 'selected' : ''}>${esc(strip.name)}</option>`).join('')}
            </select></td>
            <td><input type="number" min="0" max="255" value="${nav.index}" style="width:76px"
              data-set="nav_lights" data-m="${mi}" data-i="${ni}" data-key="index"></td>
            <td><input type="color" value="${rgbHex(nav.color)}" data-act="colour"
              data-m="${mi}" data-i="${ni}"></td>
            <td><button class="tiny danger" data-act="del" data-list="nav_lights"
              data-m="${mi}" data-i="${ni}" title="Entfernen">−</button></td>
            <td class="fill"></td>
          </tr>`).join('')}</tbody>
      </table></div>
      <div class="row" style="margin-top:10px">
        <button data-act="add-nav" data-m="${mi}" ${plane.strips.length ? '' : 'disabled'}>
          Positionslicht hinzufügen</button>
        <span class="dim" style="font-size:11.5px">Liegen über jedem Effekt und lassen sich
          nicht abschalten.</span>
      </div>
    </div></div>`;
  }).join('');

  wireModels();
  applyLock();
  $('view-models').scrollTop = scroll;
}

const zoneSelect = (zones, value, list, mi, index) =>
  `<select data-set="${list}" data-m="${mi}" data-i="${index}" data-key="zone">${
    Array.from({length: zones}, (_, zone) =>
      `<option value="${zone}" ${value === zone ? 'selected' : ''}>Zone ${zone + 1}</option>`
    ).join('')}</select>`;

const rgbHex = (colour) =>
  '#' + colour.map((value) => value.toString(16).padStart(2, '0')).join('');

/**
 * Values go straight into CONFIG and only the inline conflict marks are
 * recomputed, so typing a pin number does not tear the table out from under
 * the cursor. Structural changes rebuild the panel.
 */
function wireModels() {
  const root = $('models');

  root.querySelectorAll('[data-set]').forEach((input) => {
    const apply = () => {
      const model = CONFIG.models[+input.dataset.m];
      const value = input.type === 'checkbox' ? input.checked
        : input.type === 'number' ? +input.value
        : input.dataset.key === 'tx_port' || input.dataset.key === 'zone' ? +input.value
        : input.value;

      if (input.dataset.set === 'model') model[input.dataset.key] = value;
      else if (input.dataset.set === 'plane') model.plane[input.dataset.key] = value;
      else model.plane[input.dataset.set][+input.dataset.i][input.dataset.key] = value;

      if (input.dataset.key === 'pin' || input.dataset.key === 'sbus_pin'
          || input.dataset.key === 'name') markClashes();
    };
    input.addEventListener('change', apply);
    if (input.type === 'text' || input.type === 'number') input.addEventListener('input', apply);
  });

  root.querySelectorAll('[data-act]').forEach((element) => {
    const model = () => CONFIG.models[+element.dataset.m];

    if (element.dataset.act === 'colour') {
      element.addEventListener('change', () => {
        model().plane.nav_lights[+element.dataset.i].color =
          [1, 3, 5].map((offset) => parseInt(element.value.substr(offset, 2), 16));
      });
      return;
    }

    const actions = {
      'add-plane': () => {
        model().plane = {board: 'pico', sbus_pin: 5, pwm_pins: [10, 11, 12, 13],
          max_brightness: 200, render_hz: 200, strips: [], relays: [], nav_lights: []};
      },
      'add-strip': () => {
        const plane = model().plane;
        plane.strips.push({name: 'strip' + plane.strips.length, pin: freePin(plane),
          count: 30, zone: 0, offset: 0, reverse: false});
      },
      'add-relay': () => {
        const plane = model().plane;
        plane.relays.push({name: 'relais' + plane.relays.length, pin: freePin(plane),
          zone: 0, source: 'cue', arg: 1, threshold: 64, active_low: true,
          min_on_ms: 200, min_off_ms: 200});
      },
      'add-nav': () => model().plane.nav_lights.push({strip: 0, index: 0, color: [255, 255, 255]}),
      del: () => model().plane[element.dataset.list].splice(+element.dataset.i, 1),
      'bus-toggle': () => {
        const entry = model();
        if (entry.bus && entry.bus.enabled) entry.bus.enabled = false;
        else entry.bus = {enabled: true, relays: (entry.bus && entry.bus.relays) || []};
      },
      'bus-pick': () => applyBusChoice(model(), +element.dataset.zones,
                                       +element.dataset.relays),
    };
    element.onclick = () => { actions[element.dataset.act](); renderModels(); };
  });
}

function markClashes() {
  CONFIG.models.forEach((model, mi) => {
    if (!model.plane) return;
    const users = pinUsers(model.plane);
    $('models').querySelectorAll(`[data-m="${mi}"][data-key="pin"]`).forEach((input) => {
      const bad = (users.get(+input.value) || []).length > 1;
      input.classList.toggle('err', bad);
      const row = input.closest('tr');
      if (row) {
        row.classList.toggle('clash', bad);
        row.title = bad ? `GPIO ${input.value} doppelt: ${users.get(+input.value).join(', ')}` : '';
      }
    });
  });
}

function freePin(plane) {
  const used = new Set([0, 1, plane.sbus_pin, ...(plane.pwm_pins || []),
    ...plane.strips.map((strip) => strip.pin), ...plane.relays.map((relay) => relay.pin)]);
  for (const pin of [2, 3, 4, 6, 7, 8, 9, 14, 15, 16, 17, 18, 19, 20, 21, 22, 26, 27, 28])
    if (!used.has(pin)) return pin;
  return 2;
}

$('btn-config-save').onclick = async () => {
  const answer = await post('/api/config', {config: CONFIG});
  note($('config-note'), [answer.ok ? answer.note : answer.error], answer.ok ? 'ok' : 'err');
  if (answer.ok) { toast('Konfiguration gespeichert.', 'ok', 3000); loadConfig(); }
  else toast(answer.error, 'err', 12000);
};

$('btn-config-reload').onclick = () => {
  $('config-note').classList.add('hidden');
  loadConfig();
};

/* The wizard lives in wizard.js; this is the only way in. */
$('btn-wizard').onclick = () => {
  if (LOCKED) return toast('Während einer laufenden Show gesperrt.', 'warn', 4000);
  wizOpen();
};

/* ================================================================== Anschluss */

function fillWiringModels() {
  if (!STATE) return;
  const select = $('wiring-model');
  const previous = select.value;
  select.innerHTML = STATE.models.map((model) =>
    `<option value="${esc(model.name)}">${esc(model.name)} — Sender ${model.tx_port + 1}${
      model.has_plane ? '' : ' (keine Bordkonfiguration)'}</option>`).join('');
  if (previous && STATE.models.some((model) => model.name === previous)) select.value = previous;
}

async function loadWiring() {
  const name = $('wiring-model').value;
  const out = $('wiring-out');
  if (!name) {
    out.innerHTML = '<div class="note">Kein Modell in der Show-Konfiguration.</div>';
    return;
  }

  const answer = await api('/api/plane/' + encodeURIComponent(name));
  if (!answer.ok) {
    out.innerHTML = `<div class="note err">${esc(answer.error)}</div>`;
    return;
  }

  out.innerHTML = `
    <div class="card" style="margin-bottom:14px">
      <div class="card-head"><h2>Wo was angeschlossen wird</h2>
        <span class="grow"></span>
        <span class="dim" style="font-size:11.5px">${answer.power.pixels} Pixel ·
          Spitze ${answer.power.worst_a} A · typisch ${answer.power.typical_a} A</span></div>
      <div class="tablewrap"><table>
        <thead><tr><th>GPIO</th><th>Pin</th><th>Funktion</th><th>Angeschlossen</th><th>Hinweis</th></tr></thead>
        <tbody>${answer.wiring.map((row) => `<tr>
          <td class="n">${row.gpio >= 0 ? 'GP' + row.gpio : '—'}</td>
          <td>${esc(row.physical)}</td><td>${esc(row.role)}</td>
          <td>${esc(row.detail)}</td><td class="dim">${esc(row.note)}</td></tr>`).join('')}</tbody>
      </table></div>
      <div class="card-body" style="border-top:1px solid var(--line)">
        <p class="dim" style="margin:0;font-size:12px">Eigenes UBEC verwenden, nicht das
          Empfänger-BEC. Geschaltete Relais-Lasten kommen zum LED-Strom hinzu.</p>
      </div>
    </div>
    <div class="card" style="margin-bottom:14px">
      <div class="card-head"><h2>Auf der Kommandozeile</h2></div>
      <div class="card-body"><p class="dim" style="margin:0 0 10px;font-size:12px">Schreibt
        <code>${esc(answer.target)}</code>.</p><pre class="code">${esc(answer.build)}</pre></div>
    </div>
    <div class="card">
      <div class="card-head"><h2>Generierte config.h</h2></div>
      <div class="card-body"><pre class="code">${esc(answer.header)}</pre></div>
    </div>`;
}

$('wiring-model').onchange = loadWiring;

$('btn-write').onclick = async () => {
  const answer = await post('/api/plane/' + encodeURIComponent($('wiring-model').value));
  note($('write-note'), [answer.ok ? 'Geschrieben: ' + answer.path : answer.error],
    answer.ok ? 'ok' : 'err');
  if (answer.ok) toast('config.h geschrieben.', 'ok', 3000);
};

/* ---------------------------------------------------------- build and flash */

let jobTimer = null;

async function refreshToolchain() {
  const status = await api('/api/toolchain');
  const box = $('toolchain');
  const build = [$('btn-build-plane'), $('btn-build-ground')];
  const all = [...build, $('btn-flash-plane'), $('btn-flash-ground')];

  if (!status.local) {
    box.className = 'note warn';
    box.textContent = 'Diese Seite ist über das Netzwerk geöffnet. Bauen, Aufspielen und '
      + 'das Schreiben der config.h gehen nur direkt am Rechner, auf dem die Bridge läuft.';
    all.forEach((button) => button.disabled = true);
    $('btn-write').disabled = true;
    $('bootsel').textContent = '';
    return;
  }

  $('btn-write').disabled = false;
  $('btn-flash-plane').disabled = false;
  $('btn-flash-ground').disabled = false;

  if (!status.ok) {
    box.className = 'note err';
    box.innerHTML = 'Toolchain unvollständig: ' + esc((status.missing || []).join(', '))
      + `<br><code>${esc(status.hint)}</code>`;
    build.forEach((button) => button.disabled = true);
  } else {
    box.className = 'note hidden';
    build.forEach((button) => button.disabled = false);
  }

  $('bootsel').innerHTML = (status.bootsel || []).length
    ? `Board im Bootloader: <code>${status.bootsel.map(esc).join('</code>, <code>')}</code>`
    : 'Kein Board im Bootloader. Die <b>Bodenstation</b> kann die Bridge selbst zurücksetzen '
      + '(1200 Baud). Der <b>Pico im Flieger</b> hat kein USB-Stdio — dort BOOTSEL gedrückt '
      + 'halten und anstecken.';
}

const jobButtons = (disabled) =>
  ['btn-build-plane', 'btn-flash-plane', 'btn-build-ground', 'btn-flash-ground']
    .forEach((id) => $(id).disabled = disabled);

async function startJob(kind) {
  const log = $('job-log');
  log.classList.remove('hidden');
  log.textContent = 'wird gestartet …';

  const answer = await post('/api/job', {kind, model: $('wiring-model').value});
  if (!answer.ok) { log.textContent = answer.error; toast(answer.error, 'err', 12000); return; }

  jobButtons(true);
  if (jobTimer) clearInterval(jobTimer);
  jobTimer = setInterval(pollJob, 400);
  pollJob();
}

function stopPolling() {
  if (jobTimer) clearInterval(jobTimer);
  jobTimer = null;
  jobButtons(false);
  refreshToolchain();
}

async function pollJob() {
  const job = await api('/api/job');
  // Without this the timer would keep polling for the rest of the session.
  if (job.idle || !job.lines) { stopPolling(); return; }

  const log = $('job-log');
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.textContent = job.lines.join('\n');
  if (atBottom) log.scrollTop = log.scrollHeight;

  if (job.done) {
    log.textContent += job.ok ? '\n\n✔ fertig' : '\n\n✘ fehlgeschlagen';
    log.scrollTop = log.scrollHeight;
    toast(job.name + (job.ok ? ' — fertig' : ' — fehlgeschlagen'), job.ok ? 'ok' : 'err', 8000);
    stopPolling();
  }
}

$('btn-build-plane').onclick = () => startJob('build-plane');
$('btn-flash-plane').onclick = () => startJob('flash-plane');
$('btn-build-ground').onclick = () => startJob('build-ground');
$('btn-flash-ground').onclick = () => startJob('flash-ground');

$('btn-blackout').onclick = () => post('/api/blackout', {on: !(STATE && STATE.blackout)});

/* ==================================================================== keyboard */

document.addEventListener('keydown', (event) => {
  const tag = event.target.tagName;
  const typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes(tag) || event.target.isContentEditable;

  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault();
    if (VIEW === 'models' && !LOCKED) $('btn-config-save').click();
    else saveProject();
    return;
  }
  if (typing || event.ctrlKey || event.metaKey || event.altKey) return;

  // Blackout is a safety control and works from every view.
  if (event.key === 'b' || event.key === 'B') { $('btn-blackout').click(); return; }

  if (event.key >= '1' && event.key <= '4') { showView(VIEWS[+event.key - 1]); return; }

  // A focused button would otherwise take the space bar as a click of its own
  // and toggle the transport twice.
  if (event.code === 'Space') {
    event.preventDefault();
    if (tag === 'BUTTON') event.target.blur();
    FOLLOW = true;
    post('/api/transport',
      {action: STATE && STATE.transport && STATE.transport.playing ? 'pause' : 'play'});
    return;
  }
  if (event.key === 'Home') { event.preventDefault(); $('btn-stop').click(); return; }
  if (event.key === 'Delete' || event.key === 'Backspace') {
    if (SEL && VIEW === 'show') { event.preventDefault(); deleteSelection(); }
    return;
  }
  if (VIEW !== 'show') return;

  if (event.key === 'e' || event.key === 'E') { event.preventDefault(); addBlock(); }
  if (event.key === '+') setZoom(PPS * 1.4);
  if (event.key === '-') setZoom(PPS / 1.4);
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault();
    seekTo(Math.max(0, POSITION + (event.shiftKey ? 5 : 1) * (event.key === 'ArrowLeft' ? -1 : 1)));
  }
});

/* ====================================================================== events */

function connect() {
  const events = new EventSource('/api/events');
  events.onmessage = (message) => renderStatus(JSON.parse(message.data));
  events.onerror = () => {
    $('led-midi').className = $('led-pico').className = 'led bad';
    $('offline').classList.remove('hidden');
    // EventSource reconnects on its own; the overlay clears with the next frame.
  };
}

connect();
loadConfig();
loadProjects().then(loadProject);
