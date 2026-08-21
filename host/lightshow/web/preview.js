/* Strip preview: every chain of every model, as it would look on the aircraft.
 *
 * The Bühne view answers "what is this zone doing" -- one strip per zone, at a
 * length that stands in for the real one. This window answers the other
 * question: what does the chain soldered to GP2 actually show, all 30 pixels of
 * it, with the segments where they really sit. That is the view you need to
 * judge a lightshow without an aircraft on the bench.
 *
 * The mapping below is `outputs_show()` from firmware/plane/src/outputs.c,
 * pixel for pixel: a segment reads its zone's virtual chain at `offset`,
 * backwards when `reverse`, and anything past the end of that chain stays dark.
 * Navigation lights are stamped on top afterwards, exactly as `outputs_flush()`
 * does it. If the two ever drift apart, this window lies -- which is worse than
 * not having it.
 */

let STATE = null;
let MODEL_FILTER = null;   // null = every model
let SCALE = 1;
let TAB = 'strips';

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) =>
  ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

/* What one zone currently holds, in the 0..255 the effect engine wants.
 *
 * Comes straight from `zone_states`: the bridge reads it out of whichever
 * encoder is driving, the resting mapper or the playing timeline. It deliberately
 * does not come from the channel list -- those eight channels carry the symbols
 * of one RS(8,6) code word, and a symbol is not the value it helps encode.
 */
const zoneShow = (model, zone) => (model.zone_states || [])[zone]
  || {cue: 0, hue: 0, brightness: 0, param: 128};

/* Length of a zone's virtual chain: the furthest segment, not the sum. */
function zonePixels(model, zone) {
  let most = 0;
  for (const chain of (model.chains || [])) {
    for (const segment of chain.segments) {
      if (segment.zone !== zone) continue;
      most = Math.max(most, segment.offset + segment.count);
    }
  }
  return most;
}

/* One chain's pixels, RGB triples, the way the board would drive them. */
function chainPixels(chain, zoneFrames) {
  const out = new Uint8ClampedArray(chain.count * 3);

  for (const segment of chain.segments) {
    const frame = zoneFrames[segment.zone];
    const available = frame ? frame.length / 3 : 0;
    for (let p = 0; p < segment.count; p++) {
      const target = segment.start + p;
      if (target >= chain.count) break;
      let source = segment.reverse ? segment.count - 1 - p : p;
      source += segment.offset;
      if (source >= available) continue;          // past the zone's chain: dark
      out[target * 3] = frame[source * 3];
      out[target * 3 + 1] = frame[source * 3 + 1];
      out[target * 3 + 2] = frame[source * 3 + 2];
    }
  }

  // Navigation lights win over whatever the effects produced.
  for (const nav of (chain.nav_lights || [])) {
    if (nav.index >= chain.count) continue;
    out[nav.index * 3] = gamma(nav.color[0]);
    out[nav.index * 3 + 1] = gamma(nav.color[1]);
    out[nav.index * 3 + 2] = gamma(nav.color[2]);
  }
  return out;
}

/* The firmware gamma-corrects navigation lights too, and effects.js carries the
 * same table -- so the two match rather than merely look similar. */
const gamma = (value) => GAMMA[value & 255];

/* From what the LED emits to what the screen has to be told.
 *
 * The byte that reaches a WS2812 is its duty cycle, so it is proportional to
 * the light coming out -- a linear quantity. A screen value is not: sRGB is a
 * curve. Handing the byte straight to the canvas therefore showed a half-lit
 * strip as a quarter lit, and every mid-brightness cue came out darker and
 * flatter than it will be in the air. The model view encodes the same way in
 * its shader, so the two tabs agree.
 */
const DISPLAY = new Uint8ClampedArray(256);
for (let i = 0; i < 256; i++) {
  DISPLAY[i] = Math.round(255 * Math.pow(i / 255, 1 / 2.2));
}

/* ------------------------------------------------------------------ layout */

function build() {
  const box = $('models');
  box.innerHTML = '';
  if (!STATE) return;

  const models = STATE.models.filter(
    (model) => !MODEL_FILTER || model.name === MODEL_FILTER);

  if (!models.length) {
    box.innerHTML = '<div class="empty">Kein Modell mit Bordkonfiguration.</div>';
    return;
  }

  for (const model of models) {
    const chains = model.chains || [];
    const card = document.createElement('section');
    card.className = 'model';
    card.innerHTML = `
      <header>
        <h2>${esc(model.name)}</h2>
        <span class="dim">${model.zones} Zone${model.zones === 1 ? '' : 'n'} ·
          ${chains.length} Kette${chains.length === 1 ? '' : 'n'} ·
          ${chains.reduce((sum, c) => sum + c.count, 0)} Pixel</span>
      </header>
      ${chains.length ? '' : '<p class="empty">Keine LED-Ausgänge eingerichtet.</p>'}`;

    for (const chain of chains) {
      const row = document.createElement('div');
      row.className = 'chain';
      row.innerHTML = `
        <div class="chain-head">
          <b>${esc(chain.name)}</b>
          <span class="dim">GP${chain.pin} · ${chain.count} Pixel</span>
        </div>
        <div class="ruler">${chain.segments.map((segment) => `
          <span class="seg z${segment.zone % 8}"
            style="left:${segment.start / chain.count * 100}%;
                   width:${segment.count / chain.count * 100}%"
            title="${esc(segment.name)} — Pixel ${segment.start}–${segment.start + segment.count - 1}, Zone ${segment.zone + 1}${segment.reverse ? ', rückwärts' : ''}">
            <i>${esc(segment.name)}</i>
            <em>Z${segment.zone + 1}${segment.reverse ? ' ↔' : ''}</em>
          </span>`).join('')}
        </div>
        <canvas class="strip"></canvas>`;
      const canvas = row.querySelector('canvas');
      // Addressed by name and position, never by object: STATE is replaced
      // wholesale on every message, and a held reference would freeze at
      // whatever the first frame said.
      canvas._model = model.name;
      canvas._chainAt = model.chains.indexOf(chain);
      canvas._count = chain.count;
      card.append(row);
    }
    box.append(card);
  }
  resize();
}

/* The strips are drawn at whatever width the window offers, one rectangle per
 * pixel with a gap -- so 30 pixels look like 30 pixels, not like a gradient. */
function resize() {
  for (const canvas of document.querySelectorAll('canvas.strip')) {
    const width = canvas.parentElement.clientWidth;
    const ratio = window.devicePixelRatio || 1;
    const height = Math.max(14, Math.min(46, width / canvas._count * 1.6)) * SCALE;
    canvas.style.width = '100%';
    canvas.style.height = `${height}px`;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    canvas._ratio = ratio;
  }
}

function draw(nowMs) {
  if (STATE) {
    const frames = new Map();          // model name -> one buffer per zone
    for (const model of STATE.models) {
      // One rendered frame per zone, shared by every segment that reads it --
      // the same buffer the board would render once and push to several chains.
      const zoneFrames = [];
      for (let zone = 0; zone < model.zones; zone++) {
        const count = zonePixels(model, zone);
        if (!count) { zoneFrames.push(null); continue; }
        // Cue 0 renders black on its own, which is what an unused zone looks
        // like -- there is no failsafe to fake here, because the ground station
        // always sends a valid frame.
        zoneFrames.push(renderEffect(zoneShow(model, zone), nowMs, count,
                                     {max: model.max_brightness ?? 255}));
      }
      frames.set(model.name, zoneFrames);
    }

    if (TAB === 'strips') {
      for (const canvas of document.querySelectorAll('canvas.strip')) {
        const model = STATE.models.find((entry) => entry.name === canvas._model);
        const chain = model && (model.chains || [])[canvas._chainAt];
        if (!chain) continue;
        paint(canvas, chainPixels(chain, frames.get(model.name)));
      }
    } else {
      // One renderer for all five views; only the camera differs.
      glDraw(MOCK_VIEW, frames);
    }
  }
  requestAnimationFrame(draw);
}

function paint(canvas, pixels) {
  const ctx = canvas.getContext('2d');
  const count = pixels.length / 3;
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const pitch = w / count;
  const size = Math.max(1, pitch * 0.8);
  const radius = Math.min(size, h * 0.9) / 2;

  for (let i = 0; i < count; i++) {
    const lit = pixels[i * 3] || pixels[i * 3 + 1] || pixels[i * 3 + 2];
    const r = DISPLAY[pixels[i * 3]];
    const g = DISPLAY[pixels[i * 3 + 1]];
    const b = DISPLAY[pixels[i * 3 + 2]];
    const x = pitch * (i + 0.5);
    const y = h / 2;
    // A lit LED spills light; a dark one is a hole in the strip. Drawing the
    // glow is what makes a strobe on screen read like a strobe in the air.
    if (lit) {
      const glow = ctx.createRadialGradient(x, y, 0, x, y, radius * 2.6);
      glow.addColorStop(0, `rgba(${r},${g},${b},.55)`);
      glow.addColorStop(1, `rgba(${r},${g},${b},0)`);
      ctx.fillStyle = glow;
      ctx.fillRect(x - radius * 2.6, y - radius * 2.6, radius * 5.2, radius * 5.2);
    }
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fillStyle = lit ? `rgb(${r},${g},${b})` : 'rgba(255,255,255,.07)';
    ctx.fill();
  }
}

/* ------------------------------------------------------------------- wiring */

function fillModels() {
  const select = $('model-filter');
  const previous = select.value;
  select.innerHTML = '<option value="">Alle Modelle</option>'
    + STATE.models.map((model) =>
      `<option value="${esc(model.name)}">${esc(model.name)}</option>`).join('');
  select.value = previous;
  MODEL_FILTER = select.value || null;
}

/* What the strips look like depends on the model, not on who is playing --
 * so the window follows the same event stream as the main interface. */
function connect() {
  const events = new EventSource('/api/events');
  events.onmessage = (message) => {
    const next = JSON.parse(message.data);
    // Only the shape matters for a rebuild: values change 60 times a second and
    // redrawing the whole page for them would fight the mouse on the mockup.
    // A placement being dragged is deliberately not part of the signature --
    // the drag owns it until it lets go.
    const shape = (state) => JSON.stringify(state.models.map((model) => [
      model.name, model.zones, model.airframe,
      (model.chains || []).map((chain) => [chain.name, chain.pin, chain.count,
        chain.segments.map((s) => [s.name, s.start, s.count, s.zone,
                                   s.place && s.place.view])]),
    ]));
    const changed = !STATE || shape(next) !== shape(STATE);
    STATE = next;
    $('offline').classList.add('hidden');
    if (changed) {
      fillModels();
      mockFillModels();
      build();
      if (TAB === 'mock') mockBuild();
    }
  };
  events.onerror = () => $('offline').classList.remove('hidden');
}

for (const button of $('tabs').querySelectorAll('button')) {
  button.onclick = () => {
    TAB = button.dataset.tab;
    $('tabs').querySelectorAll('button').forEach((b) =>
      b.setAttribute('aria-pressed', String(b === button)));
    $('tab-strips').classList.toggle('hidden', TAB !== 'strips');
    $('tab-mock').classList.toggle('hidden', TAB !== 'mock');
    $('strip-tools').classList.toggle('hidden', TAB !== 'strips');
    $('mock-tools').classList.toggle('hidden', TAB !== 'mock');
    if (TAB === 'strips') resize(); else mockBuild();
  };
}

$('model-filter').onchange = (event) => {
  MODEL_FILTER = event.target.value || null;
  build();
};
$('zoom').oninput = (event) => {
  SCALE = Number(event.target.value);
  $('zoom-out').textContent = `${SCALE.toFixed(1).replace('.', ',')}×`;
  resize();
};
window.addEventListener('resize', resize);

/* WebGL once, up front: if the browser has none, the model tab says so rather
 * than showing an empty box and leaving the reason to guesswork. */
if (glInit($('mock-gl'))) {
  mockInit();
} else {
  $('mock-stage').innerHTML = '<div class="empty" style="padding:24px">'
    + 'Dieser Browser stellt kein WebGL bereit — die Modellansicht braucht es. '
    + 'Der Reiter <b>Streifen</b> funktioniert trotzdem.</div>';
  document.querySelector('#tabs button[data-tab="mock"]').disabled = true;
}

connect();
requestAnimationFrame(draw);
