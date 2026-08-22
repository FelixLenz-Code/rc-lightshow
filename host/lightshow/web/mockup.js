/* Placing segments on the model: the list, the selection, the dragging.
 *
 * The picture comes from WebGL (mockgl.js) -- airframe and lights alike, in all
 * five views. What lives here is everything you can grab: the handles and the
 * grab line, drawn in an SVG layer over the canvas and positioned through the
 * same camera the canvas used. Hit testing two circles in a shader would be a
 * great deal of machinery for two circles.
 *
 * A placement is a line: one view, two points, each 0..1 across that view's
 * window. The pixels lay themselves along it in the order the chain runs.
 *
 * Written straight into show.yaml through /api/placement, which touches that
 * one segment and nothing else -- the models view may be open in the other
 * window with unsaved edits.
 */

let MOCK_VIEW = 'top';
let MOCK_MODEL = null;      // name, or null for the first one with a board
let MOCK_SELECTED = null;   // "output/segment"
let MOCK_DRAG = null;

/* Where the turnable view is looking from. Lives here rather than in the
 * renderer because the mouse sets it and the renderer only reads it. The
 * opening angle is the three-quarter front the model magazines use: it shows
 * nose, one whole wing and one whole flank at once, so the first sight of the
 * aeroplane is the one that says the most. */
const VIEW_HOME = {yaw: 2.45, pitch: 0.38};
let YAW = VIEW_HOME.yaw;
let PITCH = VIEW_HOME.pitch;
let DIST = 4.6;

/* Back to the opening angle, and to a distance that suits whatever shape is
 * loaded. Called on the button and whenever the shape itself changes -- a
 * quadcopter framed at a glider's distance is a speck in the middle. */
function mockViewHome() {
  YAW = VIEW_HOME.yaw;
  PITCH = VIEW_HOME.pitch;
  DIST = AIRFRAME_DIST;
}

const mock3dOn = () => MOCK_VIEW === '3d';

/* Placements this window has set but not seen come back yet.
 *
 * STATE is replaced wholesale by every SSE message -- several times a second --
 * while a save is a round trip to disk. Without this a placement appears for
 * one frame and is then wiped by the next message carrying the old state, which
 * looks exactly like it never took. Cleared once the server agrees. */
const MOCK_PENDING = new Map();
const pendingKey = (model, key) => `${model}|${key}`;

const samePlace = (a, b) => (!a && !b)
  || !!(a && b && a.view === b.view
        && Math.abs(a.x1 - b.x1) < 1e-4 && Math.abs(a.y1 - b.y1) < 1e-4
        && Math.abs(a.x2 - b.x2) < 1e-4 && Math.abs(a.y2 - b.y2) < 1e-4);

const clamp01 = (value) => Math.max(0, Math.min(1, value));

/* Which shape the chosen model is drawn as. The word comes from show.yaml by
 * way of the state; anything the interface does not recognise falls back to an
 * aeroplane rather than to an empty stage. */
const mockKind = () => {
  const model = mockModel();
  return (model && model.airframe) || 'motor';
};

const mockModel = () => {
  if (!STATE) return null;
  const withBoard = STATE.models.filter((model) => (model.chains || []).length);
  return withBoard.find((model) => model.name === MOCK_MODEL) || withBoard[0] || null;
};

/* Every segment of a model, flattened, with where it sits. */
function mockSegments(model) {
  const out = [];
  (model.chains || []).forEach((chain, oi) => {
    chain.segments.forEach((segment, si) => {
      const key = `${oi}/${si}`;
      const pending = MOCK_PENDING.get(pendingKey(model.name, key));
      // What this window last set wins until the bridge reports the same.
      const place = pending !== undefined ? pending : (segment.place || null);
      if (pending !== undefined && samePlace(pending, segment.place || null)) {
        MOCK_PENDING.delete(pendingKey(model.name, key));
      }
      out.push({chain, oi, si, segment, key, place});
    });
  });
  return out;
}

/* ------------------------------------------------------------- the overlay */

function mockBuild() {
  // Never while a drag is running: rebuilding replaces the overlay, and the
  // element holding the pointer capture would go with it.
  if (MOCK_DRAG) return;
  const model = mockModel();
  // Before anything reads FLAT_VIEWS: the hints, the windows and the skin all
  // belong to the shape, and this model may not be the shape last drawn.
  if (glAirframe(mockKind())) mockViewHome();
  const svg = $('mock-svg');
  if (!model) {
    svg.innerHTML = '';
    $('mock-list').innerHTML = '<div class="empty">Kein Modell mit LED-Ausgängen.</div>';
    return;
  }

  $('mock-hint').textContent = mock3dOn()
    ? 'Alle Ansichten zusammen. Ziehen dreht, Mausrad zoomt. Platziert wird in '
      + 'den flachen Ansichten — hier steht, was daraus wird: was Du von oben '
      + 'zeichnest, liegt oben auf, was von links, an der linken Rumpfseite.'
    : FLAT_VIEWS[MOCK_VIEW].hint;

  mockBuildList();
  mockDrawOverlay();
  mockBuried();
  mockWire();
}

/* Says out loud when a drawn line asks for something the aeroplane cannot give.
 *
 * Only where the flat views do not show it: they draw their own strips without
 * a depth test, so a buried pixel looks perfectly fine there and then is missing
 * from the turnable view, which is the confusing way round. Recomputed when a
 * placement changes -- never per frame, and never during a drag. */
function mockBuried() {
  const model = mockModel();
  const box = $('mock-buried');
  if (!model) { box.textContent = ''; return; }

  const stuck = [];
  for (const entry of mockSegments(model)) {
    const p = entry.place;
    if (!p) continue;
    const n = buriedPixels(
      liftStrip(p.view, p.x1, p.y1, p.x2, p.y2, entry.segment.count));
    if (n) stuck.push(`${entry.segment.name}: ${n} von ${entry.segment.count}`);
  }
  box.textContent = stuck.length
    ? `In der Zelle statt darauf — ${stuck.join(', ')}. An dieser Stelle sitzt `
      + 'kein Streifen (meist die Flächen- oder Leitwerkswurzel, wo die Fläche '
      + 'die ganze Rumpfhöhe einnimmt). Flach ist es trotzdem zu sehen, im '
      + '3D-Bild nicht.'
    : '';
}

/* The handles, in canvas pixels. Rebuilt when the selection or the view
 * changes, and nudged in place while dragging. */
function mockDrawOverlay() {
  const svg = $('mock-svg');
  const model = mockModel();
  const canvas = $('mock-gl');
  const w = canvas.clientWidth, h = canvas.clientHeight;
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);

  if (!model || mock3dOn()) { svg.innerHTML = ''; return; }

  const here = mockSegments(model).filter(
    (entry) => entry.place && entry.place.view === MOCK_VIEW);

  svg.innerHTML = here.map((entry) => {
    const p = entry.place;
    const a = glProjectFlat(MOCK_VIEW, p.x1, p.y1, w, h);
    const b = glProjectFlat(MOCK_VIEW, p.x2, p.y2, w, h);
    const s = spinAt(a, b);
    const sel = entry.key === MOCK_SELECTED;
    // The handles are always in the markup, hidden by CSS until selected.
    // Rendering them on selection would mean rewriting the overlay at the
    // moment a drag starts -- which throws away the element holding the pointer.
    return `<g class="placed ${sel ? 'sel' : ''}" data-key="${entry.key}">
      <line class="hit" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"
        data-grab="move"/>
      <line class="stalk" x1="${s.from.x}" y1="${s.from.y}" x2="${s.x}" y2="${s.y}"/>
      <circle class="handle" data-grab="a" cx="${a.x}" cy="${a.y}" r="11"/>
      <circle class="handle" data-grab="b" cx="${b.x}" cy="${b.y}" r="11"/>
      <circle class="spin" data-grab="spin" cx="${s.x}" cy="${s.y}" r="9"/>
    </g>`;
  }).join('');
}

/* Where the turning grip goes: off the middle, square to the strip.
 *
 * Not on the line itself. Both ends already mean "aim", the middle already
 * means "move", and a strip lying along a wing is the case where turning it a
 * couple of degrees matters most -- so the grip has to be somewhere the strip
 * is not. */
function spinAt(a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const from = {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2};
  return {from, x: from.x - dy / len * 34, y: from.y + dx / len * 34};
}

function mockBuildList() {
  const model = mockModel();
  if (!model) return;
  $('mock-list').innerHTML = mockSegments(model).map((entry) => {
    const p = entry.place;
    const where = p ? FLAT_VIEWS[p.view].label : 'nicht platziert';
    return `<button class="mock-item ${entry.key === MOCK_SELECTED ? 'on' : ''}
      ${p ? '' : 'unplaced'}" data-key="${entry.key}">
      <b>${esc(entry.segment.name)}</b>
      <span>${esc(entry.chain.name)} · ${entry.segment.count} Pixel ·
        Zone ${entry.segment.zone + 1}</span>
      <em>${esc(where)}</em>
    </button>`;
  }).join('') || '<div class="empty">Dieses Modell hat keine Abschnitte.</div>';
  mockWireList();
}

/* ---------------------------------------------------------------- placement */

function mockPlace(key, place) {
  const model = mockModel();
  if (!model) return;
  const [oi, si] = key.split('/').map(Number);
  // Held here, not written into STATE: STATE is replaced by the next message.
  MOCK_PENDING.set(pendingKey(model.name, key), place);
  fetch('/api/placement', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({model: model.name, output: oi, segment: si, place}),
  }).then((r) => r.json()).then((answer) => {
    $('mock-note').textContent = answer.ok ? ''
      : (answer.error || 'nicht gespeichert');
  }).catch(() => { $('mock-note').textContent = 'nicht gespeichert'; });
}

/* Takes the chosen segment off the aeroplane again.
 *
 * Not a deletion: the segment stays, with its pixels and its zone -- what goes
 * is the line drawn for it, and it lands back in the list as "nicht platziert".
 * The turnable view cannot place, so it cannot unplace either; there is no
 * selection to act on there and the button is hidden.
 */
function mockUnplace() {
  if (!MOCK_SELECTED || mock3dOn()) return;
  mockPlace(MOCK_SELECTED, null);
  MOCK_SELECTED = null;
  mockBuild();
}

/* Where a pointer event lands, in 0..1 of the view's window. */
function mockPoint(event) {
  const canvas = $('mock-gl');
  const box = canvas.getBoundingClientRect();
  const at = glUnprojectFlat(MOCK_VIEW, event.clientX - box.left,
                             event.clientY - box.top, box.width, box.height);
  return {x: clamp01(at.u), y: clamp01(at.v)};
}

/* Turning has to happen in view units, not in the stored 0..1 -- the window is
 * wider than it is tall, so a quarter turn in placement coordinates comes out
 * as a squash. These two convert between the pair. */
/* Angle from the middle of the strip to a point, as the picture sees it. */
function turnAngle(place, at) {
  const box = FLAT_VIEWS[place.view];
  const a = viewToScreen(box, place.x1, place.y1);
  const b = viewToScreen(box, place.x2, place.y2);
  const here = viewToScreen(box, at.x, at.y);
  return Math.atan2(here.sv - (a.sv + b.sv) / 2, here.su - (a.su + b.su) / 2);
}

/* The strip turned about its own middle, keeping its length. Returns null if
 * that would take an end outside the view's window. */
function mockTurn(start, at, fromAngle, snap) {
  const box = FLAT_VIEWS[start.view];
  const a = viewToScreen(box, start.x1, start.y1);
  const b = viewToScreen(box, start.x2, start.y2);
  const mid = {su: (a.su + b.su) / 2, sv: (a.sv + b.sv) / 2};
  const half = Math.hypot(b.su - a.su, b.sv - a.sv) / 2;

  let angle = Math.atan2(b.sv - a.sv, b.su - a.su)
            + (turnAngle(start, at) - fromAngle);
  // Held down, the strip clicks into fifteens -- which is how a strip actually
  // gets fitted: along a rib, square to the spar, straight down the fuselage.
  if (snap) {
    const step = Math.PI / 12;
    angle = Math.round(angle / step) * step;
  } else {
    // Square and level have a detent of their own, without holding anything
    // down. Almost every strip is meant to be one or the other -- along the
    // span, or straight fore and aft -- and hitting that by hand within a few
    // tenths of a degree is not something a mouse can do.
    const square = Math.round(angle / (Math.PI / 2)) * (Math.PI / 2);
    if (Math.abs(angle - square) < 0.075) angle = square;   // about 4 degrees
  }

  const ends = [-1, 1].map((sign) => screenToView(box,
    mid.su + Math.cos(angle) * half * sign,
    mid.sv + Math.sin(angle) * half * sign));
  if (ends.some((e) => e.u < 0 || e.u > 1 || e.v < 0 || e.v > 1)) return null;
  return {view: start.view,
          x1: ends[0].u, y1: ends[0].v, x2: ends[1].u, y2: ends[1].v};
}

/* Moves the highlight without touching the markup that carries it. */
function mockSelect(key) {
  MOCK_SELECTED = key;
  for (const group of $('mock-svg').querySelectorAll('g.placed')) {
    group.classList.toggle('sel', group.dataset.key === key);
  }
  for (const button of $('mock-list').querySelectorAll('.mock-item')) {
    button.classList.toggle('on', button.dataset.key === key);
  }
}

function mockWire() {
  mockWireList();

  const svg = $('mock-svg');
  svg.onpointerdown = (event) => {
    const grab = event.target.dataset ? event.target.dataset.grab : null;
    if (!grab) { mockSelect(null); return; }
    const group = event.target.closest('g.placed');
    const model = mockModel();
    const entry = mockSegments(model).find(
      (item) => item.key === group.dataset.key);
    if (!entry || !entry.place) return;

    // Selection is a class change, not a rebuild: rewriting the overlay here
    // would destroy the element the pointer was just captured on.
    mockSelect(group.dataset.key);
    MOCK_DRAG = {grab, key: MOCK_SELECTED, from: mockPoint(event),
                 start: {...entry.place},
                 fromAngle: turnAngle(entry.place, mockPoint(event))};
    try { svg.setPointerCapture(event.pointerId); } catch { /* fine */ }
    event.preventDefault();
  };

  svg.onpointermove = (event) => {
    if (!MOCK_DRAG) return;
    const at = mockPoint(event);
    const s = MOCK_DRAG.start;
    let place;
    if (MOCK_DRAG.grab === 'a') place = {...s, x1: at.x, y1: at.y};
    else if (MOCK_DRAG.grab === 'b') place = {...s, x2: at.x, y2: at.y};
    else if (MOCK_DRAG.grab === 'spin') {
      place = mockTurn(s, at, MOCK_DRAG.fromAngle, event.shiftKey);
      // A turn that would push an end out of the picture is not applied at all.
      // Clamping one end and not the other would quietly shorten the strip,
      // and the pixel count would then say one thing and the drawing another.
      if (!place) return;
    } else {
      const dx = at.x - MOCK_DRAG.from.x;
      const dy = at.y - MOCK_DRAG.from.y;
      place = {view: s.view,
               x1: clamp01(s.x1 + dx), y1: clamp01(s.y1 + dy),
               x2: clamp01(s.x2 + dx), y2: clamp01(s.y2 + dy)};
    }
    MOCK_PENDING.set(pendingKey(mockModel().name, MOCK_DRAG.key), place);
    MOCK_DRAG.place = place;
    mockNudge(place);
  };

  const finish = (event) => {
    if (!MOCK_DRAG) return;
    const {key, place} = MOCK_DRAG;
    MOCK_DRAG = null;
    try { svg.releasePointerCapture(event.pointerId); } catch { /* gone */ }
    // A plain click never moved anything, so there is nothing to write.
    if (place) { mockPlace(key, place); mockBuried(); }
  };
  svg.onpointerup = finish;
  svg.onpointercancel = finish;
}

/* Moves the line and its handles during a drag, without rebuilding: a rebuild
 * would drop the pointer capture and the drag would stop dead. */
function mockNudge(place) {
  const group = $('mock-svg').querySelector(
    `g.placed[data-key="${CSS.escape(MOCK_DRAG.key)}"]`);
  if (!group) return;
  const canvas = $('mock-gl');
  const w = canvas.clientWidth, h = canvas.clientHeight;
  const a = glProjectFlat(MOCK_VIEW, place.x1, place.y1, w, h);
  const b = glProjectFlat(MOCK_VIEW, place.x2, place.y2, w, h);
  const line = group.querySelector('line.hit');
  line.setAttribute('x1', a.x); line.setAttribute('y1', a.y);
  line.setAttribute('x2', b.x); line.setAttribute('y2', b.y);
  const handles = group.querySelectorAll('circle.handle');
  if (handles[0]) { handles[0].setAttribute('cx', a.x); handles[0].setAttribute('cy', a.y); }
  if (handles[1]) { handles[1].setAttribute('cx', b.x); handles[1].setAttribute('cy', b.y); }
  const spin = spinAt(a, b);
  const grip = group.querySelector('circle.spin');
  if (grip) { grip.setAttribute('cx', spin.x); grip.setAttribute('cy', spin.y); }
  const stalk = group.querySelector('line.stalk');
  if (stalk) {
    stalk.setAttribute('x1', spin.from.x); stalk.setAttribute('y1', spin.from.y);
    stalk.setAttribute('x2', spin.x); stalk.setAttribute('y2', spin.y);
  }
}

function mockWireList() {
  for (const button of $('mock-list').querySelectorAll('.mock-item')) {
    button.onclick = () => {
      const model = mockModel();
      const entry = mockSegments(model).find(
        (item) => item.key === button.dataset.key);
      if (!entry) return;
      if (!entry.place) {
        // Not placed yet: drop it across the middle of a flat view, where it is
        // immediately visible and immediately draggable. The turnable view
        // cannot take one, so it lands on the top.
        const view = mock3dOn() ? 'top' : MOCK_VIEW;
        mockPlace(button.dataset.key,
                  {view, x1: 0.35, y1: 0.5, x2: 0.65, y2: 0.5});
        MOCK_VIEW = view;
      } else if (!mock3dOn() && entry.place.view !== MOCK_VIEW) {
        // Follow it to where it lives rather than pretending it is not there.
        MOCK_VIEW = entry.place.view;
      }
      mockSyncButtons();
      MOCK_SELECTED = button.dataset.key;
      mockBuild();
    };
  }
}

function mockSyncButtons() {
  $('mock-views').querySelectorAll('button').forEach((b) =>
    b.setAttribute('aria-pressed', String(b.dataset.view === MOCK_VIEW)));
  // The turnable view has nothing to grab, so the cursor says "turn me".
  $('mock-stage').classList.toggle('stage-3d', mock3dOn());
  $('mock3d-reset').classList.toggle('hidden', !mock3dOn());
  $('mock-clear').classList.toggle('hidden', mock3dOn());
}

/* ------------------------------------------------------------------ wiring */

function mockInit() {
  $('mock-views').innerHTML = Object.entries(FLAT_VIEWS).map(([key, view]) =>
    `<button data-view="${key}" aria-pressed="${key === MOCK_VIEW}"
      >${esc(view.label)}</button>`).join('')
    + `<button data-view="3d" aria-pressed="false" title="Alle Ansichten
        zusammen, drehbar mit der Maus">3D</button>`;

  for (const button of $('mock-views').querySelectorAll('button')) {
    button.onclick = () => {
      MOCK_VIEW = button.dataset.view;
      mockSyncButtons();
      mockBuild();
    };
  }

  $('mock-model').onchange = (event) => {
    MOCK_MODEL = event.target.value || null;
    MOCK_SELECTED = null;
    mockBuild();
  };

  $('mock-clear').onclick = mockUnplace;

  // How much light there is besides the strips. Low by default: a lightshow is
  // flown after dark, and the window is only worth anything if what it shows is
  // the same balance the audience will see.
  const ambient = $('mock-ambient');
  const setAmbient = () => {
    // Squared, so the bottom half of the travel -- where the interesting
    // difference between "silhouette" and "just visible" lives -- gets half the
    // slider instead of a few pixels of it.
    const t = Number(ambient.value);
    GL_AMBIENT = 0.35 + 11 * t * t;
    $('mock-ambient-out').textContent = t < 0.02 ? 'aus'
      : `${Math.round(t * 100)} %`;
  };
  ambient.oninput = setAmbient;
  setAmbient();

  $('mock3d-reset').onclick = mockViewHome;

  // Turning happens on the canvas, because in 3D the overlay is out of the way.
  const canvas = $('mock-gl');
  let turning = null;
  canvas.onpointerdown = (event) => {
    if (!mock3dOn()) {
      // Anywhere off a strip means "done with that one". The overlay itself
      // cannot report this: it lets the pointer through everywhere except on a
      // handle, precisely so that dragging in the 3D view reaches the canvas --
      // so the click that puts a segment down arrives here.
      mockSelect(null);
      return;
    }
    turning = {x: event.clientX, y: event.clientY, yaw: YAW, pitch: PITCH};
    try { canvas.setPointerCapture(event.pointerId); } catch { /* fine */ }
    event.preventDefault();
  };
  canvas.onpointermove = (event) => {
    if (!turning) return;
    YAW = turning.yaw - (event.clientX - turning.x) * 0.008;
    // Stopped short of straight up and down: past the pole the model flips and
    // the mouse suddenly means the opposite of what it did.
    PITCH = Math.max(-1.4, Math.min(1.4,
      turning.pitch + (event.clientY - turning.y) * 0.008));
  };
  const stop = (event) => {
    turning = null;
    try { canvas.releasePointerCapture(event.pointerId); } catch { /* gone */ }
  };
  canvas.onpointerup = stop;
  canvas.onpointercancel = stop;
  canvas.onwheel = (event) => {
    if (!mock3dOn()) return;
    event.preventDefault();
    // The limits follow the shape too, or a quadcopter cannot be come near and
    // a glider cannot be got away from.
    DIST = Math.max(AIRFRAME_DIST * 0.45, Math.min(AIRFRAME_DIST * 2.6,
      DIST * (event.deltaY > 0 ? 1.1 : 1 / 1.1)));
  };

  window.addEventListener('keydown', (event) => {
    const tag = event.target.tagName;
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(tag)) return;
    if (!MOCK_SELECTED || MOCK_DRAG) return;
    if (event.key === 'Escape') mockSelect(null);
    // Entf nimmt den gewählten Abschnitt vom Flugzeug -- dasselbe, was der
    // Knopf tut, nur ohne den Weg zur Leiste. Rückschritt zählt mit, weil das
    // im Zeitachsen-Fenster auch löscht.
    if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      mockUnplace();
    }
  });

  window.addEventListener('resize', () => { if (!MOCK_DRAG) mockDrawOverlay(); });
  mockSyncButtons();
}

function mockFillModels() {
  const select = $('mock-model');
  const previous = select.value;
  select.innerHTML = STATE.models
    .filter((model) => (model.chains || []).length)
    .map((model) => `<option value="${esc(model.name)}">${esc(model.name)}</option>`)
    .join('');
  if (previous) select.value = previous;
  MOCK_MODEL = select.value || null;
}
