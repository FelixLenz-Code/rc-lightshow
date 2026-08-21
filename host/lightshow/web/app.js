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
  // Der Abspielkopf vor der Drossel: er ist das, worauf das Auge liegt, und
  // kostet eine Transformation. Die LED-Vorschauen dahinter kosten mehr und
  // kommen mit dreissig Bildern aus.
  if (CLOCK && VIEW === 'show') {
    const at = CLOCK.at + (now - CLOCK.stamp) / 1000;
    POSITION = at;
    refreshPlayhead(at);
    $('clock').textContent = fmtTime(at);
    followPlayhead(at);
  }

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

/* The bridge reports the position five times a second. Drawing the playhead
   only then makes it hop in eight pixel steps at the standard zoom, which is
   what a playhead must not do -- it is the one thing on screen the eye follows.
   So the last report is kept with the moment it arrived, and the frame loop
   carries it forward from there. Each new report puts it right again; on
   loopback the correction is a millisecond or two, well under a pixel. */
let CLOCK = null;         // {at, stamp} -- last word from the bridge

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

/* ====================================================================== quit */

/* Two steps, because there is no undo: a stray click leaves dark models on the
   field and the way back is a terminal. In the second step the confirming
   button sits left of "Abbrechen", so clicking the same spot twice cancels
   instead of switching the bridge off. */

let SHUTDOWN = false;
let EVENTS = null;

function quitStep(which) {
  ['quit-step1', 'quit-step2'].forEach(
    (id) => $(id).classList.toggle('hidden', id !== which));
}

$('btn-quit').onclick = () => {
  const live = !!(STATE && STATE.locked);
  $('quit-playing').classList.toggle('hidden', !live);
  quitStep('quit-step1');
  $('quit').showModal();
};

$('quit-cancel1').onclick = () => $('quit').close();
$('quit-cancel2').onclick = () => $('quit').close();
$('quit-next').onclick = () => quitStep('quit-step2');

$('quit-confirm').onclick = async () => {
  $('quit-confirm').disabled = true;
  const answer = await post('/api/quit');
  if (!answer.ok) {
    $('quit-confirm').disabled = false;
    toast(answer.error || 'Ausschalten abgelehnt', 'err');
    return;
  }
  SHUTDOWN = true;
  if (EVENTS) EVENTS.close();     // sonst versucht der Browser ewig weiter
  // Nur eine Meldung: die Sperrfläche deckt den ganzen Schirm und lässt sich
  // nicht wegklicken, ein Dialog davor sagte dasselbe noch einmal.
  $('quit').close();
  showOffline();
};

function showOffline() {
  $('led-pico').className = 'led bad';
  $('offline-title').textContent = SHUTDOWN ? 'Bridge ausgeschaltet'
                                            : 'Bridge nicht erreichbar';
  $('offline-lost').classList.toggle('hidden', SHUTDOWN);
  $('offline-off').classList.toggle('hidden', !SHUTDOWN);
  $('offline').classList.remove('hidden');
}

/* ===================================================================== views */

const VIEWS = ['show', 'projects', 'stage', 'models', 'wiring'];

function showView(name) {
  VIEW = name;
  document.querySelectorAll('.rail button.nav').forEach((button) =>
    button.setAttribute('aria-selected', String(button.dataset.view === name)));
  VIEWS.forEach((other) => $('view-' + other).classList.toggle('hidden', other !== name));
  $('project-bar').classList.toggle('hidden', name !== 'show');

  if (name === 'projects') loadProjects();
  if (name === 'wiring') { fillWiringModels(); loadWiring(); refreshToolchain(); }
  if (name === 'stage' && STATE) renderStage(STATE);
  if (name === 'show') layoutTimeline();
}

document.querySelectorAll('.rail button.nav').forEach((button) => {
  button.onclick = () => showView(button.dataset.view);
});

/* ================================================================== projects */

let applyTimer = null;
let saveTimer = null;
let lastApplyError = '';
let PROJECTS = [];        // what /api/projects last said, for the tab
let PROJECT_MODELS = [];  // and which models a new one could be built from
let PROJECT_OPEN = null;  // the folder name of the open project

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
  showProjectState();
  if (!dirty) return;
  clearTimeout(applyTimer);
  applyTimer = setTimeout(pushEdit, 300);
  // And on disk. Separate timer and a longer wait on purpose: the apply above
  // is what makes an edit audible and has to be quick, while writing is what
  // makes it survive and can wait for the hand to come off the mouse. Dragging
  // a block across a minute of timeline is one write, not ninety.
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => saveProject({quiet: true}), 900);
}

/* The one thing the show bar still says: which project, and whether the disk
 * has caught up with the screen. */
function showProjectState() {
  $('project-name').textContent = PROJ ? PROJ.name : 'keines geöffnet';
  const state = $('project-state');
  $('btn-project-close').classList.toggle('hidden', !PROJ);
  if (!PROJ) { state.textContent = ''; return; }
  state.textContent = DIRTY ? 'wird gespeichert …' : 'gespeichert';
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

async function loadProjects() {
  const answer = await api('/api/projects');
  PROJECTS = answer.projects || [];
  PROJECT_MODELS = answer.models || [];
  PROJECT_OPEN = answer.open || null;
  renderProjects();
}

function renderProjects() {
  const box = $('projects');
  if (!PROJECTS.length) {
    box.innerHTML = `<div class="note">Noch kein Projekt.
      <b>＋ Neues Projekt</b> fragt nach einem Namen und den Modellen und legt
      die Spuren an.</div>`;
    return;
  }
  box.innerHTML = PROJECTS.map(projectCard).join('');
  box.querySelectorAll('button[data-open]').forEach((button) => {
    button.onclick = () => openProject(button.dataset.open);
  });
  box.querySelectorAll('button[data-sweep]').forEach((button) => {
    button.onclick = async () => {
      const dir = button.dataset.sweep;
      const entry = PROJECTS.find((p) => p.dir === dir) || {};
      if (!confirm(`${entry.spare_audio} Audiodatei(en) aus `
          + `projects/${dir}/audio löschen? Kein Clip zeigt darauf, `
          + 'zurückholen lässt sich das nicht.')) return;
      const answer = await post('/api/project/sweep-audio', {dir});
      if (!answer.ok) return toast(answer.error, 'err', 10000);
      await loadProjects();
      toast(`${answer.files.length} Datei(en) gelöscht, `
            + `${megabytes(answer.bytes)} frei.`, 'ok', 5000);
    };
  });
  box.querySelectorAll('button[data-export]').forEach((button) => {
    button.onclick = async () => {
      const dir = button.dataset.export;
      if (await saveFrom('/api/project/export/' + encodeURIComponent(dir),
                         `${dir}.zip`, ZIP_TYPES))
        toast(`Projekt '${dir}' gespeichert.`, 'ok', 3000);
    };
  });
  // Any project, open or not. Having to load one first would mean playing it by
  // accident and losing the place in the one that was already there, for the
  // sake of renaming it.
  box.querySelectorAll('button[data-edit]').forEach((button) => {
    button.onclick = () => {
      if (LOCKED) return toast('Während einer laufenden Show gesperrt.', 'warn', 4000);
      const dir = button.dataset.edit;
      const entry = PROJECTS.find((p) => p.dir === dir);
      if (!entry) return;
      // The open one is edited through what the editor holds, so a rename lands
      // on the same object the timeline is drawn from; a closed one out of what
      // the listing says, which is name and models -- all the dialogue asks for.
      const held = dir === PROJECT_OPEN && PROJ ? PROJ : entry;
      pwOpen(PROJECT_MODELS, held, dir);
    };
  });
}

function projectCard(entry) {
  const open = entry.dir === PROJECT_OPEN;
  const models = entry.models && entry.models.length
    ? entry.models.map(esc).join(', ')
    : '<span class="warn-text">kein Modell eingetragen</span>';
  return `<div class="card model-row">
    <div class="card-head">
      <h2>${esc(entry.name)}</h2>
      ${open ? '<span class="tag ok-text">geöffnet</span>' : ''}
      <span class="grow"></span>
      <button class="quiet" data-export="${esc(entry.dir)}"
        title="Als Zip mit Musik und Spuren sichern">Exportieren</button>
      <button data-edit="${esc(entry.dir)}">Bearbeiten</button>
      <button data-open="${esc(entry.dir)}" ${open ? 'class="quiet"' : ''}
        >${open ? 'Erneut laden' : 'Öffnen'}</button>
    </div>
    <div class="card-body">
      <div class="model-facts">
        <span>Modelle <b>${models}</b></span>
        <span>${entry.tracks} Spur${entry.tracks === 1 ? '' : 'en'}</span>
        <span class="dim">projects/${esc(entry.dir)}</span>
      </div>
      ${entry.spare_audio ? `<div class="note" style="margin-top:10px">
        ${entry.spare_audio} Audiodatei${entry.spare_audio === 1 ? '' : 'en'}
        (${megabytes(entry.spare_bytes)}) im Projektordner, auf die kein Clip
        zeigt. Eine Datei, die aus der Timeline fliegt, wird mitgelöscht — das
        hier lag schon vorher da oder wurde von Hand hineinkopiert.
        <button class="quiet" data-sweep="${esc(entry.dir)}"
          style="margin-left:8px">Aufräumen</button>
      </div>` : ''}
    </div>
  </div>`;
}

const megabytes = (bytes) => bytes >= 1024 * 1024
  ? `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`
  : `${Math.max(1, Math.round(bytes / 1024))} kB`;

/* Puts the show down without putting anything else up.
 *
 * The bridge hands the audio device back and falls to the resting state,
 * which is what it does with no project at all. */
async function closeProject() {
  if (!PROJ) return;
  const name = PROJ.name;
  clearTimeout(saveTimer);
  // Anything still in the 900 ms window would otherwise be lost.
  if (DIRTY) await saveProject({quiet: true});
  const answer = await post('/api/project/close');
  if (!answer.ok) return toast(answer.error || 'nicht geschlossen', 'err', 8000);
  PROJECT_OPEN = null;
  applyProject(null);
  renderProjects();
  toast(`Projekt „${name}“ geschlossen.`, 'ok', 3000);
}

async function openProject(dir) {
  if (!dir) return;
  // Nothing to warn about any more: an edit is on disk within a second of
  // being made, so switching project cannot lose one.
  const answer = await post('/api/project/open', {dir});
  if (!answer.ok) return toast(answer.error, 'err');
  markDirty(false);
  applyProject(answer.project);
  PROJECT_OPEN = dir;
  renderProjects();
  showView('show');
  toast(`Projekt „${answer.project.data.name}“ geöffnet.`, 'ok', 3000);
}

const LIST_NAMES = {audio: 'audio_tracks', light: 'light_tracks',
                    relay: 'relay_tracks'};

/** Which of the project's three track lists this one is in. */
function listNameOf(track) {
  if (PROJ.audio_tracks.includes(track)) return 'audio';
  if (PROJ.light_tracks.includes(track)) return 'light';
  return 'relay';
}

function selectionAddress() {
  if (!SEL || !PROJ) return null;
  const list = listNameOf(SEL.track);
  const tracks = PROJ[LIST_NAMES[list]] || [];
  const trackIndex = tracks.indexOf(SEL.track);
  if (trackIndex < 0) return null;
  if (SEL.kind === 'track') return {kind: 'track', list, track: trackIndex};
  const items = SEL.kind === 'clip' ? SEL.track.clips : SEL.track.blocks;
  return {kind: SEL.kind, list, track: trackIndex, item: items.indexOf(SEL.item)};
}

function restoreSelection(address) {
  if (!address || !PROJ) return;
  const tracks = PROJ[LIST_NAMES[address.list]] || [];
  const track = tracks[address.track];
  if (!track) return;
  if (address.kind === 'track') { SEL = {kind: 'track', track}; return; }
  const items = address.kind === 'clip' ? track.clips : track.blocks;
  const item = items[address.item];
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
  PROJECT_OPEN = payload.dir || PROJECT_OPEN;

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

/* Hands the browser a file to save.
 *
 * A link with `download` rather than anything cleverer: the interface is served
 * from the same machine the file is on, so there is nothing to arrange -- the
 * browser asks where to put it and that is the whole transaction.
 */
function download(url, filename) {
  const link = document.createElement('a');
  link.href = url;
  if (filename) link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
}

/* Fragt, wohin die Datei soll.
 *
 * Ein <a download> fragt nicht: der Browser legt die Datei dort ab, wo er
 * Downloads ablegt, und meldet das in einer Blase an der Werkzeugleiste -- die
 * es im eigenen Anwendungsfenster gar nicht gibt, weshalb dort nicht einmal zu
 * sehen ist, dass etwas passiert ist. `showSaveFilePicker` gibt es in der
 * Chromium-Familie und braucht einen sicheren Kontext; 127.0.0.1 gilt als
 * einer. Wo es das nicht gibt, bleibt es beim alten Weg.
 *
 * Rueckgabe: der Dateigriff, `null` nach Abbruch, `undefined` wenn dieser
 * Browser nicht fragen kann.
 */
async function askWhereToSave(filename, types) {
  if (!window.showSaveFilePicker) return undefined;
  try {
    return await window.showSaveFilePicker({suggestedName: filename, types});
  } catch (error) {
    // Abbrechen ist keine Panne; alles andere (etwa eine abgelaufene
    // Nutzergeste) faellt auf den Download zurueck.
    return error.name === 'AbortError' ? null : undefined;
  }
}

const JSON_TYPES = [{description: 'Lightshow-Modell',
                     accept: {'application/json': ['.json']}}];
const ZIP_TYPES = [{description: 'Lightshow-Projekt',
                    accept: {'application/zip': ['.zip']}}];

/** True, wenn gespeichert wurde -- false nur bei Abbruch. */
async function saveJson(data, filename) {
  const text = JSON.stringify(data, null, 2);
  const handle = await askWhereToSave(filename, JSON_TYPES);
  if (handle === null) return false;
  if (handle) {
    try {
      const writable = await handle.createWritable();
      await writable.write(text);
      await writable.close();
    } catch (error) {
      toast(`Speichern fehlgeschlagen: ${error.message}`, 'err', 8000);
      return false;
    }
    return true;
  }
  download(URL.createObjectURL(
    new Blob([text], {type: 'application/json'})), filename);
  return true;
}

/* Dasselbe fuer etwas, das die Bridge liefert. Der Inhalt wird durchgereicht,
 * nicht erst eingesammelt: ein Projekt bringt seine Audiodateien mit und kann
 * dreistellige Megabytes haben. */
async function saveFrom(url, filename, types) {
  const handle = await askWhereToSave(filename, types);
  if (handle === null) return false;
  if (!handle) { download(url, filename); return true; }

  const response = await fetch(url);
  if (!response.ok) {
    toast(`Speichern fehlgeschlagen (HTTP ${response.status}).`, 'err', 8000);
    return false;
  }
  try {
    await response.body.pipeTo(await handle.createWritable());
  } catch (error) {
    toast(`Speichern fehlgeschlagen: ${error.message}`, 'err', 8000);
    return false;
  }
  return true;
}

async function exportModel(name) {
  const answer = await api('/api/model/export/' + encodeURIComponent(name));
  if (!answer.ok) return toast(answer.error, 'err', 8000);
  if (await saveJson(answer.document, `${name}.lightshow-modell.json`))
    toast(`Modell '${name}' exportiert.`, 'ok', 3000);
}

/* Reads a file the user picked and hands it to the bridge.
 *
 * Both importers report what they had to change rather than only whether it
 * worked: two configurations that never met collide on nearly everything, and
 * a model that was quietly renumbered is a model answering to a channel nobody
 * expects. */
$('btn-model-import').onclick = () => $('file-model').click();
$('file-model').onchange = async (event) => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  let document_;
  try {
    document_ = JSON.parse(await file.text());
  } catch (error) {
    return toast(`${file.name} ist keine lesbare Modelldatei: ${error}`, 'err', 10000);
  }
  const answer = await post('/api/model/import', {document: document_});
  if (!answer.ok) return toast(answer.error, 'err', 12000);
  await loadConfig();
  const notes = answer.notes || [];
  note($('config-note'), [`Modell '${answer.name}' importiert.`, ...notes],
       notes.length ? 'warn' : 'ok');
  toast(`Modell '${answer.name}' importiert.`, 'ok', 4000);
};

$('btn-project-import').onclick = () => $('file-project').click();
$('file-project').onchange = async (event) => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  const answer = await (await fetch('/api/project/import?name='
    + encodeURIComponent(file.name.replace(/\.lightshow-projekt\.zip$|\.zip$/, '')),
    {method: 'POST', body: await file.arrayBuffer()})).json();
  if (!answer.ok) return toast(answer.error, 'err', 12000);
  await loadProjects();
  const notes = answer.notes || [];
  toast(`Projekt „${answer.name}“ importiert.`
        + (notes.length ? ' ' + notes.join(' · ') : ''),
        notes.length ? 'warn' : 'ok', notes.length ? 12000 : 4000);
};

$('btn-project-close').onclick = () => closeProject();

/* The wizard lives in projectwiz.js; this is the only way in. */
$('btn-project-create').onclick = () => {
  if (LOCKED) return toast('Während einer laufenden Show gesperrt.', 'warn', 4000);
  pwOpen(PROJECT_MODELS);
};

/* Writes the project.
 *
 * Called on a timer after every edit, and by Ctrl+S for anyone who does not
 * believe it. The saved project is deliberately *not* read back into the
 * editor: the answer is the same thing that was sent, and reapplying it would
 * rebuild every track element and take the selection with it -- in the middle
 * of the drag that triggered the save.
 */
async function saveProject({quiet = false} = {}) {
  if (!PROJ) return false;
  const answer = await post('/api/project', {project: PROJ});
  if (!answer.ok) {
    // Left dirty on purpose: the timer will try again on the next edit, and
    // the show bar keeps saying so in the meantime.
    toast(answer.error, 'err', 12000);
    return false;
  }
  clearTimeout(saveTimer);
  DIRTY = false;
  showProjectState();
  // Worth saying out loud: the file is gone from the disk, not just from the
  // timeline, and that is not something to find out later.
  const gone = answer.removed_audio || [];
  if (gone.length) {
    toast(`${gone.map((f) => f.replace(/^audio\//, '')).join(', ')} `
          + `${gone.length === 1 ? 'wird' : 'werden'} nicht mehr gebraucht und `
          + `${gone.length === 1 ? 'wurde' : 'wurden'} aus dem Projekt gelöscht.`,
          'ok', 7000);
  }
  if (!quiet) toast('Gespeichert.', 'ok', 2000);
  return true;
}

/* ============================================================ timeline model */

const MIN_LENGTH = 0.1;

/** The relay a relay track drives, as the state payload describes it. */
function relayOf(track) {
  const model = STATE && STATE.models.find((entry) => entry.name === track.model);
  return model && model.relays ? model.relays[track.relay] || null : null;
}

const relayName = (track) => {
  const relay = relayOf(track);
  return relay ? `${track.model} · ${relay.name}` : `${track.model} Relais ${track.relay + 1}`;
};

function laneList() {
  if (!PROJ) return [];
  return [
    ...PROJ.audio_tracks.map((track, index) => ({kind: 'audio', track, index})),
    ...PROJ.light_tracks.map((track, index) => ({kind: 'light', track, index})),
    ...(PROJ.relay_tracks || []).map((track, index) => ({kind: 'relay', track, index})),
  ];
}

function itemsOf(lane) {
  return lane.kind === 'audio' ? lane.track.clips : lane.track.blocks;
}

/** The project list a track belongs to, whatever kind it is. */
function listOf(track) {
  if (PROJ.audio_tracks.includes(track)) return PROJ.audio_tracks;
  if (PROJ.light_tracks.includes(track)) return PROJ.light_tracks;
  return PROJ.relay_tracks || [];
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
  for (const track of (PROJ.relay_tracks || []))
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
    lanes.innerHTML = '<div class="empty">Kein Projekt geöffnet. Im Reiter '
      + '<b>Projekte</b> eines öffnen oder anlegen.<br>'
      + '<span class="dim">Solange keines offen ist, bleiben die Lichter '
      + 'im Ruhezustand.</span></div>';
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
  head.classList.toggle('relay', lane.kind === 'relay');
  if (SEL && SEL.kind === 'track' && SEL.track === lane.track) head.classList.add('sel');

  const name = document.createElement('div');
  name.className = 'hn';
  name.textContent = lane.kind === 'audio'
    ? (lane.track.name || `Audio ${lane.index + 1}`)
    : lane.kind === 'relay'
      ? (lane.track.name || relayName(lane.track))
      : (lane.track.name || lane.track.model);

  const sub = document.createElement('div');
  sub.className = 'hs';
  // Der Text steckt in einem eigenen Element, damit er sich kuerzen kann, ohne
  // den Stummschalter mitzunehmen.
  const text = document.createElement('span');
  text.className = 'ht';
  sub.append(text);

  if (lane.kind === 'audio') {
    const gain = lane.track.gain_db;
    text.append(gain ? `${gain > 0 ? '+' : ''}${gain} dB` : 'Audio');
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
  } else if (lane.kind === 'relay') {
    const relay = relayOf(lane.track);
    if (!relay) text.append('⚠ Relais gibt es nicht mehr');
    else {
      text.append(`GP${relay.pin} · Bit ${lane.track.relay}`);
      head.title = `${lane.track.model} · ${relay.name} · GP${relay.pin} · `
        + `CC ${relay.cc}${relay.active_low ? ' · schaltet bei LOW' : ''}`;
    }
  } else {
    const model = STATE && STATE.models.find((entry) => entry.name === lane.track.model);
    const outputs = zoneOutputs(lane.track);
    if (!model) text.append('⚠ unbekanntes Modell');
    else if (outputs && outputs.strips.length) {
      text.append(outputs.strips.map((strip) => strip.name).join(' + '));
      head.title = `Sender ${model.tx_port + 1} · Kanal ${model.first_channel}`
        + `–${model.last_channel} · ${describeOutputs(outputs)}`;
    } else text.append(`Sender ${model.tx_port + 1}`);
    if (model && model.zones > 1) text.append(` · Z${lane.track.zone + 1}`);
  }

  // Gekuerzt heisst nicht unlesbar.
  if (text.textContent) text.title = text.textContent;

  head.append(name, sub);
  head.onclick = () => selectTrack(lane.track);
  return head;
}

function buildLane(lane) {
  const element = document.createElement('div');
  element.className = 'lane'
    + (lane.kind === 'audio' ? ' audio' : lane.kind === 'relay' ? ' relay' : '');
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
  element._lane = lane;
  return element;
}

function buildItem(lane, item) {
  const node = document.createElement('div');
  node.className = 'item'
    + (lane.kind === 'audio' ? ' clip' : lane.kind === 'relay' ? ' switched' : '');

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
  } else if (lane.kind === 'relay') {
    // A relay is on or off, so there is no colour to derive and no level to
    // report -- the block itself is the whole statement.
    parts.cap.textContent = item.label || 'an';
    parts.cap2.textContent = '';
  } else {
    node.style.background = blockColour(item, 0.35);
    parts.cap.textContent = item.label || cueName(item.cue);
    parts.cap2.textContent = width > 92
      ? `${fmtTime(length)} · ${Math.round(item.brightness / 255 * 100)} %` : '';
  }

  // A relay has no fades; the fields simply are not there on its blocks.
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
  $('playhead').style.transform = `translateX(${(at * PPS).toFixed(2)}px)`;
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
  SEL = {kind: lane.kind === 'audio' ? 'clip' : lane.kind === 'relay' ? 'switch'
           : 'block', track: lane.track, item};
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

/** Keeps the fades inside their block; the bridge rejects anything else.
 *  A switch block has no fades at all, and must not be given any. */
function fitFades(item) {
  if (item.fade_in_s === undefined) return;
  const total = item.fade_in_s + item.fade_out_s;
  if (total <= item.duration_s || total <= 0) return;
  const factor = item.duration_s / total;
  item.fade_in_s = round3(item.fade_in_s * factor);
  item.fade_out_s = round3(item.fade_out_s * factor);
}

/* Wohin ein Block beim Loslassen darf.
 *
 * Ein Lichtblock traegt Cue, Farbton, Helligkeit und Tempo -- den kann jede
 * Lichtspur nehmen, auch die eines anderen Modells. Ein Relaisblock ist ein
 * Zustand und gehoert auf eine Relaisspur, ein Clip auf eine Audiospur. Ueber
 * die Grenze hinweg gibt es nichts zu uebertragen. */
const laneTakes = (from, to) => from.kind === to.kind;

function laneElementUnder(clientY) {
  for (const element of $('tl-lanes').children) {
    if (!element._lane) continue;
    const box = element.getBoundingClientRect();
    if (clientY >= box.top && clientY < box.bottom) return element;
  }
  return null;
}

/* Schiebt einen Block auf die erste Luecke, in die er passt.
 *
 * Dasselbe, was ein neuer Effekt tut: zwei Bloecke duerfen sich nicht
 * ueberlappen, sonst laesst sich das Projekt nicht speichern. Auf einer neuen
 * Spur ist die gezogene Stelle oft belegt, und ein Block, der beim Loslassen
 * verschwindet, waere schlimmer als einer, der ein Stueck weiterrutscht. */
function slideIntoGap(track, block) {
  for (const other of [...track.blocks].sort((a, b) => a.start_s - b.start_s)) {
    if (other === block) continue;
    const end = round3(other.start_s + other.duration_s);
    if (block.start_s < end && other.start_s < block.start_s + block.duration_s)
      block.start_s = end;
  }
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
  const origin = {start: item.start_s, length: item.duration_s,
                  x: event.clientX, y: event.clientY};
  let moved = false;

  // Senkrecht gezogen wechselt der Block die Spur. Bis zum Loslassen bleibt er
  // in seiner eigenen und wird nur verschoben dargestellt -- ihn mitten in der
  // Geste umzuhaengen kostet in manchen Browsern die Zeigererfassung.
  let target = null;                 // Ziel-Spurelement, oder null fuer "bleibt"
  const markTarget = (element, on) =>
    element && element.classList.toggle('drop', on);

  node.setPointerCapture(event.pointerId);
  node.style.zIndex = '6';
  event.preventDefault();

  const onMove = (move) => {
    const delta = (move.clientX - origin.x) / PPS;
    if (Math.abs(move.clientX - origin.x) > 2
        || Math.abs(move.clientY - origin.y) > 2) moved = true;
    const free = move.altKey;

    if (mode === 'move') {
      const over = laneElementUnder(move.clientY);
      const next = over && over._lane !== lane && laneTakes(lane, over._lane)
        ? over : null;
      if (next !== target) {
        markTarget(target, false);
        target = next;
        markTarget(target, true);
      }
      node.style.transform = target
        ? `translateY(${(target.getBoundingClientRect().top
                         - node.parentElement.getBoundingClientRect().top).toFixed(1)}px)`
        : '';

      // Beim Spurwechsel gelten die Nachbarn der Zielspur noch nicht -- der
      // Block darf frei stehen und rueckt beim Loslassen in die erste Luecke.
      let start = snapTime(origin.start + delta, free);
      if (!target)
        start = clamp(start, bounds.before,
                      Math.max(bounds.before, bounds.after - origin.length));
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
    markTarget(target, false);
    node.style.transform = '';
    node.style.zIndex = '';
    if (!moved) { target = null; return; }    // a plain click only selects
    fitFades(item);

    const landed = target && target._lane;
    target = null;

    if (landed) {
      const from = itemsOf(lane);
      from.splice(from.indexOf(item), 1);
      const into = itemsOf(landed);
      into.push(item);
      if (landed.kind !== 'audio') {
        slideIntoGap(landed.track, item);
        into.sort((a, b) => a.start_s - b.start_s);
      }
      markDirty();
      // Der Block gehoert jetzt einer anderen Spur -- das ist mehr, als sich
      // an Ort und Stelle richten laesst.
      buildTimeline();
      selectItem(laneOf(landed.track), item);
    } else {
      if (lane.kind !== 'audio') lane.track.blocks.sort((a, b) => a.start_s - b.start_s);
      markDirty();
      layoutItem(node);
      layoutTimeline();
    }
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
  // The one save whose answer is worth reading back: it carries the waveform
  // the new clip has to be drawn with.
  const answer2 = await post('/api/project', {project: PROJ});
  if (answer2.ok) { clearTimeout(saveTimer); applyProject(answer2.project); }
  else toast(answer2.error, 'err', 12000);
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
$('btn-add-relay').onclick = () => addRelayTrack();

/* Adds a block to whichever track is selected. A relay track takes a switch
 * block, a light track an effect block -- the same button, because from the
 * user's side it is the same gesture. */
function addBlock(onTrack, atSeconds) {
  if (!PROJ) return toast('Erst ein Projekt öffnen.', 'err');
  const relays = PROJ.relay_tracks || [];
  const chosen = onTrack || (SEL && SEL.track);
  const onRelay = chosen && relays.includes(chosen);
  if (!onRelay && !PROJ.light_tracks.length)
    return toast('Erst eine Lichtspur anlegen (+L).', 'err');

  const track = onRelay ? chosen
    : (chosen && PROJ.light_tracks.includes(chosen) ? chosen : PROJ.light_tracks[0]);
  const start = snapTime(atSeconds !== undefined ? atSeconds : POSITION, false);

  const block = onRelay
    ? {start_s: start, duration_s: 2, label: ''}
    : {
        start_s: start, duration_s: 4, cue: 1, hue: 0,
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

function availableRelays() {
  const out = [];
  for (const model of (STATE ? STATE.models : []))
    for (let relay = 0; relay < (model.relays || []).length; relay++)
      out.push({model: model.name, relay});
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

function addRelayTrack() {
  if (!PROJ) return toast('Erst ein Projekt öffnen.', 'err');
  if (!PROJ.relay_tracks) PROJ.relay_tracks = [];
  const all = availableRelays();
  if (!all.length)
    return toast('Kein Modell hat ein Relais — im Tab Modelle eins einrichten.', 'err');

  const taken = new Set(PROJ.relay_tracks.map((track) => `${track.model}/${track.relay}`));
  const free = all.find((entry) => !taken.has(`${entry.model}/${entry.relay}`));
  if (!free) return toast('Für jedes Relais gibt es bereits eine Spur.', 'err');

  const model = STATE.models.find((entry) => entry.name === free.model);
  const relay = model.relays[free.relay];
  PROJ.relay_tracks.push({
    model: free.model, relay: free.relay, blocks: [],
    name: `${free.model} · ${relay.name}`,
  });
  markDirty();
  buildTimeline();
  selectTrack(PROJ.relay_tracks[PROJ.relay_tracks.length - 1]);
}

/* ============================================================ Kontextmenü */

/* Was hier drinsteht, hängt daran, worauf geklickt wurde: auf einem Block gibt
   es etwas zu duplizieren und zu löschen, auf leerer Spur etwas einzufügen.
   Alle Einträge rufen dieselben Funktionen wie die Knöpfe und Tasten -- das
   Menü ist ein zweiter Weg zu denselben Handgriffen, keine zweite Fassung. */

function closeMenu() {
  $('ctx').classList.add('hidden');
}

function openMenu(x, y, entries) {
  const menu = $('ctx');
  menu.innerHTML = '';
  for (const entry of entries) {
    if (!entry) continue;
    if (entry === '-') {
      // Kein Strich als Erstes und keine zwei hintereinander -- die Einträge
      // davor können alle weggefallen sein.
      if (menu.lastElementChild && menu.lastElementChild.tagName === 'BUTTON')
        menu.append(document.createElement('hr'));
      continue;
    }
    const button = document.createElement('button');
    button.type = 'button';
    button.setAttribute('role', 'menuitem');
    if (entry.danger) button.className = 'danger';
    button.append(entry.label);
    if (entry.key) {
      const key = document.createElement('span');
      key.className = 'key';
      key.textContent = entry.key;
      button.append(key);
    }
    button.disabled = !!entry.disabled;
    button.onclick = () => { closeMenu(); entry.run(); };
    menu.append(button);
  }

  if (menu.lastElementChild && menu.lastElementChild.tagName === 'HR')
    menu.lastElementChild.remove();

  // Erst zeigen, dann einpassen: vorher hat der Kasten keine Maße.
  menu.classList.remove('hidden');
  menu.style.left = '0px';
  menu.style.top = '0px';
  const box = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(x, window.innerWidth - box.width - 8)}px`;
  menu.style.top = `${Math.min(y, window.innerHeight - box.height - 8)}px`;
}

function duplicateItem(lane, item) {
  const copy = JSON.parse(JSON.stringify(item));
  const list = itemsOf(lane);
  const length = lane.kind === 'audio' ? clipLength(lane.track, item) : item.duration_s;
  copy.start_s = round3(item.start_s + length);
  list.push(copy);
  list.sort((a, b) => a.start_s - b.start_s);
  markDirty();
  buildTimeline();
  selectItem(lane, copy);
}

function menuEntries(lane, item, at) {
  const kind = lane && lane.kind;
  const insert = kind === 'audio'
    ? {label: 'Musik einfügen …', run: () => pickAudio(lane, snapTime(at, false))}
    : {label: kind === 'relay' ? 'Relaisblock einfügen' : 'Effekt einfügen',
       key: 'E', run: () => addBlock(lane && lane.track, at)};

  return [
    lane ? insert : null,
    item ? {label: 'Duplizieren', run: () => duplicateItem(lane, item)} : null,
    item ? {label: 'Löschen', key: 'Entf', danger: true,
            run: () => { selectItem(lane, item); deleteSelection(); }} : null,
    '-',
    {label: 'Abspielkopf hierher', run: () => seekTo(snapTime(at, false), true)},
    {label: SNAP ? 'Raster aus' : 'Raster an', run: () => $('btn-snap').click()},
    lane ? '-' : null,
    lane ? {label: 'Spureinstellungen', run: () => selectTrack(lane.track)} : null,
    lane ? {label: 'Spur löschen', danger: true,
            run: () => { selectTrack(lane.track); deleteSelection(); }} : null,
  ];
}

function wireMenu() {
  const open = (event) => {
    if (!PROJ) return;
    event.preventDefault();
    const node = event.target.closest('.item');
    const laneEl = event.target.closest('.lane');
    const head = event.target.closest('.head');
    const lane = node ? node._lane : laneEl ? laneEl._lane
      : head ? laneList()[[...$('tl-heads').children].indexOf(head)] : null;
    if (node) selectItem(node._lane, node._item);
    // Über einem Spurkopf steht der Zeiger auf keiner Zeit -- dort gilt, wo
    // der Abspielkopf ohnehin schon steht.
    const at = head ? POSITION : timeAtClientX(event.clientX);
    openMenu(event.clientX, event.clientY, menuEntries(lane, node && node._item, at));
  };
  $('tl-lanes').addEventListener('contextmenu', open);
  $('tl-heads').addEventListener('contextmenu', open);
  $('tl-ruler').addEventListener('contextmenu', open);

  // Wegklicken, wegtippen, wegrollen -- ein Menü, das stehen bleibt, ist im Weg.
  document.addEventListener('pointerdown', (event) => {
    if (!event.target.closest('#ctx')) closeMenu();
  }, true);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeMenu();
  });
  $('tl').addEventListener('scroll', closeMenu, {passive: true});
}
wireMenu();

function deleteSelection() {
  if (!SEL || !PROJ) return;

  if (SEL.kind === 'track') {
    const list = listOf(SEL.track);
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
  else if (SEL.kind === 'switch') renderSwitchInspector();
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

/* A relay block has three things to say: when it starts, how long it stays on
 * and what to call it. No effect, no colour, no fades -- a switch has none. */
function renderSwitchInspector() {
  const block = SEL.item;
  const relay = relayOf(SEL.track);
  $('insp-kind').textContent = 'Schaltblock';
  $('insp-title').textContent = SEL.track.name || relayName(SEL.track);

  $('insp-body').innerHTML = `
    <div class="note" style="margin:0 0 14px">${relay
      ? `<b>${esc(relay.name)}</b> ist während dieses Blocks <b>an</b> — Bit `
        + `${SEL.track.relay} im Rahmen, GP${relay.pin}.`
        + ((relay.min_on_ms || relay.min_off_ms)
          ? `<br><span class="dim">Träges Relais: mindestens ${relay.min_on_ms} ms an, `
            + `${relay.min_off_ms} ms aus. Kürzere Blöcke werden an Bord gedehnt.</span>` : '')
      : 'Dieses Relais gibt es am Modell nicht (mehr).'}</div>

    <div class="f"><label class="lbl">Beschriftung</label>
      <input type="text" data-key="label" value="${esc(block.label)}"
             placeholder="an" style="width:100%"></div>

    <div class="fgrid">
      ${numberField('Start (s)', block.start_s, 'start_s', 0.05)}
      ${numberField('Länge (s)', block.duration_s, 'duration_s', 0.05, MIN_LENGTH)}
    </div>

    <div class="row" style="margin-top:6px">
      <button class="danger" id="insp-del">Block löschen</button>
      <span class="dim" style="font-size:11.5px">Ende ${fmtTime(block.start_s + block.duration_s)}</span>
    </div>`;

  wireInspector((key, value) => {
    block[key] = value;
    if (key === 'start_s' || key === 'duration_s') {
      clampBlock(SEL.track, block);
      SEL.track.blocks.sort((a, b) => a.start_s - b.start_s);
    }
    const shown = $('insp-body').querySelector(`[data-show="${key}"]`);
    if (shown) shown.textContent = value;
    markDirty();
    refreshItem(block);
    layoutTimeline();
  });
  $('insp-del').onclick = deleteSelection;
}

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
  });
  $('insp-del').onclick = deleteSelection;
}

const modelCeiling = (track) => {
  const model = STATE && STATE.models.find((entry) => entry.name === track.model);
  return model ? (model.max_brightness ?? 255) : 255;
};

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
  const list = listNameOf(track);
  const isAudio = list === 'audio';
  $('insp-kind').textContent = isAudio ? 'Audiospur'
    : list === 'relay' ? 'Relaisspur' : 'Lichtspur';
  $('insp-title').textContent = track.name || track.model || '—';

  if (list === 'relay') {
    const models = STATE ? STATE.models : [];
    const model = models.find((entry) => entry.name === track.model);
    const relays = (model && model.relays) || [];
    const relay = relays[track.relay];
    $('insp-body').innerHTML = `
      <div class="f"><label class="lbl">Name</label>
        <input type="text" data-key="name" value="${esc(track.name)}"
               placeholder="${esc(relayName(track))}" style="width:100%"></div>
      <div class="f"><label class="lbl">Modell</label>
        <select data-key="model" style="width:100%">${models.map((entry) =>
          `<option value="${esc(entry.name)}" ${entry.name === track.model ? 'selected' : ''}
            >${esc(entry.name)} — Sender ${entry.tx_port + 1}</option>`
        ).join('') || `<option>${esc(track.model)}</option>`}</select></div>
      <div class="f"><label class="lbl">Relais</label>
        <select data-key="relay" style="width:100%">${relays.map((entry, index) =>
          `<option value="${index}" ${track.relay === index ? 'selected' : ''}
            >${esc(entry.name)} — GP${entry.pin}</option>`
        ).join('') || `<option>Relais ${track.relay + 1}</option>`}</select></div>
      <div class="f"><label class="lbl">Schaltet</label>
        <div class="note" style="margin:0">${relay
          ? `Bit ${track.relay} im Rahmen, Control-Change ${relay.cc}, GP${relay.pin}`
            + (relay.active_low ? ' — Modul schaltet bei LOW' : '')
            + ((relay.min_on_ms || relay.min_off_ms)
              ? `<br>träge: min ${relay.min_on_ms}/${relay.min_off_ms} ms` : '')
          : 'Dieses Relais gibt es am Modell nicht (mehr).'}</div></div>
      ${model ? '' : `<div class="note err">Das Modell „${esc(track.model)}“ steht nicht in
        der Show-Konfiguration — diese Spur schaltet nichts.</div>`}
      <div class="row"><button class="danger" id="insp-del">Spur löschen</button>
        <span class="dim" style="font-size:11.5px">${track.blocks.length} Block/Blöcke</span></div>`;
  } else if (isAudio) {
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
        <div class="note" style="margin:0">${esc(describeOutputs(zoneOutputs(track)))}</div></div>
      ${model ? '' : `<div class="note err">Das Modell „${esc(track.model)}“ steht nicht in
        der Show-Konfiguration — diese Spur steuert nichts.</div>`}
      <div class="row"><button class="danger" id="insp-del">Spur löschen</button>
        <span class="dim" style="font-size:11.5px">${track.blocks.length} Block/Blöcke</span></div>`;
  }

  wireInspector((key, value) => {
    track[key] = (key === 'zone' || key === 'relay') ? +value : value;
    markDirty();
    // Model, zone and relay change what the track drives, so the lanes are
    // rebuilt. Name, gain and mute only relabel the head -- redrawing
    // everything there would tear the field out from under the cursor mid-word.
    if (key === 'model' || key === 'zone' || key === 'relay') {
      buildTimeline();
      renderInspector();
    } else refreshHead(track);
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
  // `transport.rate` wäre hier falsch: das ist die Abtastrate der Soundkarte,
  // nicht ein Tempo. Die Show läuft in Echtzeit.
  CLOCK = transport.playing ? {at, stamp: performance.now()} : null;
  $('clock').textContent = fmtTime(at);
  // With nothing open there is nothing to be "of", and the last project's
  // length standing next to "kein Projekt geöffnet" reads as a contradiction.
  $('clock-total').textContent = PROJ ? 'von ' + fmtTime(transport.duration) : '';
  // Beim Spielen gehört der Kopf der Bildschleife -- hier gesetzt liefe er
  // gegen die Zwischenwerte und zappelte.
  if (!transport.playing) refreshPlayhead(at);

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
 * two strips.
 *
 * The four channel entries come along for the raw table, but the values that
 * get rendered come from `zone_states` -- what the driving encoder holds. The
 * channels themselves only carry the resting state: while the timeline plays,
 * nobody touches them, and reading the wire instead would hand back the
 * symbols of an RS(8,6) code word rather than anything you could show. */
function zonesOf(model) {
  const out = [];
  const states = model.zone_states || [];
  for (let start = 0; start + 4 <= model.channels.length; start += 4) {
    const four = model.channels.slice(start, start + 4);
    const by = (role) => four.find((channel) => channel.role === role);
    const index = out.length;
    const state = states[index] || {cue: 0, hue: 0, brightness: 0, param: 128};
    out.push({
      index,
      cue: by('cue'), hue: by('hue'),
      brightness: by('brightness'), param: by('param'),
      channels: four,
      state,
    });
  }
  return out;
}

const zoneShow = (zone) => ({
  cue: zone.state.cue,
  hue: zone.state.hue,
  brightness: zone.state.brightness,
  param: zone.state.param,
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
            <span class="tag" title="Alle Zonen dieses Modells teilen sich diesen codierten Block">Kanal ${model.first_channel}–${model.last_channel}</span>
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
              <thead><tr><th>Rolle</th><th>CC</th><th class="n">µs</th><th>Wert</th></tr></thead>
              <tbody></tbody></table></div>
          </details>`;
        $('stage').append(card);

        // The card keeps rendering from whatever the newest frame says.
        card._zone = zone;
        card._max = model.max_brightness ?? 255;
        preview(card.querySelector('canvas'), () => {
          const current = card._zone;
          if (!current) return null;
          // Blackout is the one state the bridge can show as such; cue 0 draws
          // itself black, and losing the radio is not visible from here.
          if (card._blackout) return {failsafe: true, max: card._max};
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
      card._blackout = !!state.blackout;
      updatePlaneCard(card, zone, !!state.blackout);
    }
  }
}

function updatePlaneCard(card, zone, blackout) {
  const show = zoneShow(zone);
  // The ground station always sends a valid frame, so there is no "no signal"
  // to show from here -- that is the radio's business, and the radio is past
  // this end of the wire. What there is: blackout, and plain off.
  const dark = blackout || !show.cue || !show.brightness;
  // Amber for blackout, the zone's own hue while it shows something, and a
  // neutral grey when it is simply off -- hue 0 is red, and a red dot beside
  // the word "aus" reads as an alarm.
  const [r, g, b] = blackout ? [255, 120, 0]
    : dark ? [70, 76, 88] : hsv(show.hue, 255);

  card.classList.toggle('offline', dark);
  card.querySelector('.cn').textContent = blackout ? 'Blackout'
    : show.cue ? cueName(show.cue) : 'aus';
  const swatch = card.querySelector('.swatch');
  swatch.style.background = `rgb(${r},${g},${b})`;
  swatch.style.color = `rgb(${r},${g},${b})`;

  const meter = (name, fraction, text, hue) => {
    const box = card.querySelector('.meter.' + name);
    box.classList.toggle('off', dark);
    box.querySelector('i').style.width = (clamp(fraction, 0, 1) * 100).toFixed(1) + '%';
    box.querySelector('.v').textContent = text;
    if (hue) box.querySelector('.t').style.setProperty('--hue', hue);
  };
  meter('hue', show.hue / 255, String(show.hue), `rgb(${r},${g},${b})`);
  meter('bri', show.brightness / 255, Math.round(show.brightness / 255 * 100) + ' %');
  meter('par', show.param / 255, (periodMs(show.param) / 1000).toFixed(2) + ' s');

  card.querySelector('tbody').innerHTML = zone.channels.map((channel) => `
    <tr><td>${esc(channel.role)}</td>
      <td class="n">${channel.us}</td>
      <td class="${channel.live ? '' : 'dim'}">${channel.live ? esc(channel.decoded)
        : 'Ruhezustand'}</td>
    </tr>`).join('');
}

function renderConnections(state) {
  const pico = state.pico;
  const rows = [
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
  box.textContent = 'Es läuft eine Show. Die Bearbeitung ist gesperrt, damit '
    + 'sich die Zuordnung nicht mitten in der Show verschiebt.';
  $('models').querySelectorAll('input, select, button')
    .forEach((element) => element.disabled = LOCKED);
  $('btn-model-import').disabled = LOCKED;
  // Creating a project lays out tracks from the configuration, so it waits for
  // the same quiet moment an edit to the configuration does.
  $('btn-project-create').disabled = LOCKED;
}

/* =============================================================== models view */

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
    <thead><tr><th class="bus-corner">Zonen \\ Bus-Relais</th>${head}</tr></thead>
    <tbody>${rows}</tbody>
  </table></div>
  <p class="dim" style="font-size:11.5px;margin:6px 0 0">
    Zahlen sind Millisekunden, bis dieselbe Zone wieder an der Reihe ist.
    — heißt: passt nicht ins Bitbudget. Gezählt werden nur Relais, die ein
    eigenes Bit brauchen; Relais, die einem Effekt folgen, kosten nichts und
    stehen hier nicht.</p>`;
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
/* id 0 sits on GPIO2, id 1 on GPIO3 and so on -- see hardware/README.md. */
const portGpio = (id) => 2 + id;

/* Ready-made boards, straight from /api/config. */
let BOARDS = [];
let FREE_BOARD = 'pico';

/* [255, 0, 0] -> "#ff0000", for the colour inputs. */
const rgbHex = (colour) =>
  '#' + colour.map((value) => value.toString(16).padStart(2, '0')).join('');

async function loadConfig() {
  const answer = await api('/api/config');
  if (!answer.config) return toast(answer.error || 'Konfiguration nicht lesbar', 'err');
  CONFIG = answer.config;
  // Which boards exist and where their connectors go is the server's answer,
  // the same one it validates against. The wizard only adds the picture.
  BOARDS = answer.boards || [];
  FREE_BOARD = answer.free_board || 'pico';
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
  (plane.outputs || []).forEach((output) => add(output.pin, `Ausgang „${output.name}“`));
  plane.relays.forEach((relay) => add(relay.pin, `Relais „${relay.name}“`));
  return users;
}

/* The overview is a list, not an editor.
 *
 * It used to be every setting of every aircraft laid out at once, which meant
 * the same fields existed twice -- here and in the wizard -- and the two drifted.
 * Now this answers "what is in this show, and is anything obviously wrong", and
 * Bearbeiten hands the whole aircraft to the wizard.
 */
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

  // Not a warning any more. Several models on one jack is a normal thing to
  // build: they share the transmitter and take different channel blocks out of
  // the same frame, which the configuration check enforces. What it does mean
  // is that they are alternatives, so a project takes one of them, not both --
  // and that is where it is said, in the project wizard.
  const warning = shared.length ? `<div class="note">
    ${shared.map(([port, names]) => `Sender-Buchse ${port + 1} tragen sich
      <b>${names.map(esc).join('</b> und <b>')}</b> zusammen.`).join('<br>')}
    Das geht, solange sich ihre Kanalblöcke nicht überschneiden — darauf achtet
    der Wizard, und die Konfiguration weist es sonst ab. Weil sie sich denselben
    Sender teilen, kommt in ein Projekt aber immer nur eines davon.</div>` : '';

  const empty = `<div class="note">Noch kein Modell. <b>＋ Neues Modell</b> führt
    durch Fernsteuerung, Zonen, LED-Ausgänge, Relais und Positionslichter.</div>`;

  $('models').innerHTML = warning + (CONFIG.models.length
    ? CONFIG.models.map(modelCard).join('') : empty);

  $('models').querySelectorAll('button[data-act]').forEach((button) => {
    button.onclick = () => {
      if (LOCKED) return toast('Während einer laufenden Show gesperrt.', 'warn', 4000);
      const name = button.dataset.model;
      if (button.dataset.act === 'edit') return wizOpen(name);
      if (button.dataset.act === 'export') return exportModel(name);
      if (!confirm(`Modell '${name}' wirklich entfernen?`)) return;
      const gone = CONFIG.models.find((model) => model.name === name);
      CONFIG.models = CONFIG.models.filter((model) => model.name !== name);
      if (gone) freeJack(gone.tx_port);
      renderModels();
      saveConfig({quiet: true}).then((ok) => {
        if (ok) toast(`Modell '${name}' entfernt und gespeichert.`, 'ok', 5000);
      });
    };
  });

  wireModelDetails();
  applyLock();
  $('view-models').scrollTop = scroll;
}

/* Gibt die Buchse eines entfernten Modells wieder frei.
 *
 * Der Assistent schaltet eine Buchse an, wenn ein Modell sie belegt -- nichts
 * schaltete sie je wieder aus. Zurueck blieb eine Buchse, die im Assistenten
 * als belegt dasteht und in der Anschlussuebersicht Kanaele fuehrt, die
 * niemand mehr sendet; das sieht aus, als waere das Modell gar nicht weg.
 *
 * Nur die Buchse dieses Modells, und nur wenn kein anderes sie noch benutzt.
 * Name, Kanalzahl und Rahmenlaenge bleiben stehen: die beschreiben die Buchse
 * und den Sender, nicht das Modell, das zufaellig daran hing.
 */
function freeJack(id) {
  if (CONFIG.models.some((model) => model.tx_port === id)) return;
  const port = (CONFIG.tx_ports || []).find((entry) => entry.id === id);
  if (port) port.format = 'off';
}

/* The headline facts, and any problem visible without opening the model. */
function modelCard(model) {
  const plane = model.plane;
  const zones = Math.max(1, Math.floor(model.channels.length / 4));
  const busRelays = ((model.bus && model.bus.relays) || []).length;
  const port = (CONFIG.tx_ports || []).find((entry) => entry.id === model.tx_port);
  const last = model.tx_offset + 8;

  const facts = [`${zones} Zone${zones === 1 ? '' : 'n'}`];
  if (plane) {
    const outputs = plane.outputs || [];
    const pixels = outputs.reduce((sum, output) => sum + output.count, 0);
    const segments = outputs.reduce((sum, output) => sum + output.segments.length, 0);
    facts.push(outputs.length
      ? `${outputs.length} ${outputs.length === 1 ? 'LED-Ausgang' : 'LED-Ausgänge'},
         ${segments} Abschnitt${segments === 1 ? '' : 'e'}, ${pixels} Pixel`
      : 'keine LED-Ausgänge');
    if (plane.relays.length) facts.push(`${plane.relays.length} Relais`);
    if (busRelays) facts.push(`${busRelays} davon am Bus`);
    if (plane.nav_lights.length)
      facts.push(`${plane.nav_lights.length} Positionslicht${
        plane.nav_lights.length === 1 ? '' : 'er'}`);
  }
  if (port) facts.push(`${busLatency(zones, port.frame_us).toFixed(0)} ms je Zone`);

  // Two pins on one job is the one mistake a list can still catch, and it makes
  // the firmware misbehave rather than fail, so it is worth saying out loud.
  const clashes = plane ? [...pinUsers(plane).entries()]
    .filter(([, who]) => who.length > 1)
    .map(([pin, who]) => `GPIO ${pin}: ${who.join(', ')}`) : [];

  return `<div class="card model-row">
    <div class="card-head">
      <h2>${esc(model.name)}</h2>
      ${plane ? '' : '<span class="tag warn-text">keine Bordkonfiguration</span>'}
      <span class="grow"></span>
      <button class="quiet" data-act="export" data-model="${esc(model.name)}"
        title="Als Datei sichern, um es woanders einzulesen">Exportieren</button>
      <button data-act="edit" data-model="${esc(model.name)}">Bearbeiten</button>
      <button class="quiet danger" data-act="del" data-model="${esc(model.name)}"
        title="Modell aus der Show entfernen">Entfernen</button>
    </div>
    <div class="card-body">
      <div class="model-facts">
        <span>Sender-Buchse <b>${model.tx_port + 1}</b> · GP${portGpio(model.tx_port)}</span>
        <span>Kanal <b>${model.tx_offset + 1}–${last}</b></span>
        ${facts.map((fact) => `<span>${fact}</span>`).join('')}
      </div>
      ${clashes.length ? `<div class="note err" style="margin-top:10px">
        Doppelt belegte Anschlüsse: ${clashes.join(' · ')}</div>` : ''}
    </div>
    ${plane ? `<details data-wiring="${esc(model.name)}"
      style="border-top:1px solid var(--line)">
      <summary class="card-head" style="cursor:pointer">
        <h2 style="font-size:13px">Wo was angeschlossen wird</h2>
        <span class="grow"></span>
      </summary>
      <div class="card-body"><div class="dim" style="font-size:12px">wird geladen …</div></div>
    </details>` : ''}
  </div>`;
}

/* The wiring table, fetched when somebody actually opens it.
 *
 * It lives on the model rather than on the flashing page, because it is a
 * property of the aircraft and not of the firmware: which GPIO carries which
 * chain is what you look at with a soldering iron in hand, and it does not
 * change by building anything. Fetched lazily because a page of model cards
 * would otherwise be one request per model on every render.
 */
function wireModelDetails() {
  $('models').querySelectorAll('details[data-wiring]').forEach((box) => {
    box.ontoggle = async () => {
      if (!box.open || box.dataset.loaded) return;
      box.dataset.loaded = '1';
      const body = box.querySelector('.card-body');
      const answer = await api('/api/plane/' + encodeURIComponent(box.dataset.wiring));
      if (!answer.ok) {
        body.innerHTML = `<div class="note err">${esc(answer.error)}</div>`;
        return;
      }
      body.innerHTML = `
        <div class="dim" style="font-size:11.5px;margin-bottom:8px">
          ${answer.power.pixels} Pixel · Spitze ${answer.power.worst_a} A ·
          typisch ${answer.power.typical_a} A</div>
        <div class="tablewrap"><table>
          <thead><tr><th>GPIO</th><th>Pin</th><th>Funktion</th><th>Angeschlossen</th><th>Hinweis</th></tr></thead>
          <tbody>${answer.wiring.map((row) => `<tr>
            <td class="n">${row.gpio >= 0 ? 'GP' + row.gpio : '—'}</td>
            <td>${esc(row.physical)}</td><td>${esc(row.role)}</td>
            <td>${esc(row.detail)}</td><td class="dim">${esc(row.note)}</td></tr>`).join('')}</tbody>
        </table></div>
        <p class="dim" style="margin:10px 0 0;font-size:12px">Eigenes UBEC verwenden,
          nicht das Empfänger-BEC. Geschaltete Relais-Lasten kommen zum LED-Strom hinzu.</p>`;
    };
  });
}

/* How long until the same zone is addressed again: one zone per RC frame. */
const busLatency = (zones, frameUs) => zones * (frameUs || 35500) / 1000;

/* Writes the configuration, and says whether it landed.
 *
 * Called after every change to the model list. A model is not a draft the way
 * a timeline is: there is one aircraft, it either has three zones or four, and
 * a list that shows four while the file says three is a trap -- it is exactly
 * the state in which somebody generates a config.h and wonders why the
 * aircraft disagrees. So the list writes as it goes.
 *
 * And when a write is refused -- the bridge takes no configuration while a show
 * is running -- the list is put back to what the file says rather than left
 * holding a change nobody can see. There is no save button to retry with, and
 * a browser quietly holding the only copy of an edit is the trap all over
 * again, one screen further along.
 */
async function saveConfig({quiet = false} = {}) {
  const answer = await post('/api/config', {config: CONFIG});
  note($('config-note'), [answer.ok ? answer.note : answer.error], answer.ok ? 'ok' : 'err');
  if (!answer.ok) {
    toast(`${answer.error} — die Änderung wurde verworfen, die Liste zeigt `
          + 'wieder, was in der Datei steht.', 'err', 14000);
  } else if (!quiet) {
    toast('Konfiguration gespeichert.', 'ok', 3000);
  }
  loadConfig();
  return !!answer.ok;
}

/* A second window rather than a panel: it is meant to sit on another screen
 * while the timeline is edited on this one, and a panel cannot do that. Reusing
 * the same window name means clicking again focuses the one already open
 * instead of piling up copies. */
let PREVIEW_WINDOW = null;
$('btn-preview').onclick = () => {
  if (PREVIEW_WINDOW && !PREVIEW_WINDOW.closed) { PREVIEW_WINDOW.focus(); return; }
  PREVIEW_WINDOW = window.open('preview.html', 'lightshow-preview',
                               'width=980,height=760');
  if (!PREVIEW_WINDOW) toast('Der Browser hat das Fenster blockiert.', 'warn', 6000);
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
  $('plane-target').textContent = '';
  if (!name) {
    out.innerHTML = '<div class="note">Kein Modell in der Show-Konfiguration.</div>';
    return;
  }

  const answer = await api('/api/plane/' + encodeURIComponent(name));
  if (!answer.ok) {
    out.innerHTML = `<div class="note err">${esc(answer.error)}</div>`;
    return;
  }

  $('plane-target').textContent = answer.target;
  // What is left here is firmware and nothing else: the command line that does
  // the same thing outside the interface, and the header that comes out. Where
  // the wires go is a property of the model, and lives on the model's card.
  out.innerHTML = `
    <div class="card" style="margin-bottom:14px">
      <div class="card-head"><h2>Auf der Kommandozeile</h2>
        <span class="grow"></span>
        <span class="dim" style="font-size:11.5px">dasselbe ohne diese Oberfläche</span></div>
      <div class="card-body"><p class="dim" style="margin:0 0 10px;font-size:12px">Schreibt
        <code>${esc(answer.target)}</code>.</p><pre class="code">${esc(answer.build)}</pre></div>
    </div>
    <details class="card">
      <summary class="card-head" style="cursor:pointer"><h2>Generierte config.h</h2>
        <span class="grow"></span>
        <span class="dim" style="font-size:11.5px">${answer.header.split('\n').length} Zeilen</span>
      </summary>
      <div class="card-body"><pre class="code">${esc(answer.header)}</pre></div>
    </details>`;
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
    // Both halves write themselves; the shortcut only answers the reflex.
    if (VIEW === 'models') toast('Modelle werden von selbst gespeichert.', 'ok', 2500);
    else saveProject();          // already on a timer; this is for the fingers
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
    if (event.repeat) return;          // hält jemand die Taste, ist das eine Ansage
    FOLLOW = true;
    // Die Bridge entscheidet, was das Gegenteil des Jetzigen ist -- hier wäre
    // das Wissen bis zu 200 ms alt, und zwei Anschläge kurz hintereinander
    // schickten dann zweimal 'play'.
    post('/api/transport', {action: 'toggle'});
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
  EVENTS = new EventSource('/api/events');
  EVENTS.onmessage = (message) => renderStatus(JSON.parse(message.data));
  EVENTS.onerror = () => {
    // EventSource reconnects on its own; the overlay clears with the next
    // frame. After a deliberate shutdown there is nothing to come back, and
    // showOffline() says so instead of talking about a broken connection.
    showOffline();
  };
}

connect();
loadConfig();
loadProjects().then(loadProject);
