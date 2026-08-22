/* Model wizard: builds -- or reworks -- a complete aircraft, step by step.
 *
 * Assembling one by hand means knowing which channels are free, how long a PPM
 * frame has to be for them, and how a zone count trades against relay bits in
 * one payload. That is a lot to hold in the head at once, and
 * every one of those answers already exists on the server -- so the wizard asks
 * rather than guesses. Nothing here re-implements a rule: frame lengths and the
 * zone/relay budget come from /api/bus.
 *
 * It is also the only editor for a model. The overview lists aircraft and their
 * headline facts; everything that can be changed is changed in here, so there
 * is one place to learn rather than two that half overlap.
 *
 * The result goes into CONFIG and takes effect on Speichern, like every other
 * edit in the models view.
 */

const WIZ_STEPS = ['Bauart', 'Fernsteuerung', 'Zonen', 'LED-Ausgänge', 'Relais',
                   'Positionslichter'];

/* A ready-made board has its pins in the copper, so the wizard fills them in
 * instead of asking -- and the steps after this one stop offering choices the
 * board has already made. The free build is the way out: a bare Pico wired by
 * hand, where every pin is open again.
 *
 * Which boards exist and where their connectors go comes from the server, in
 * BOARDS/FREE_BOARD -- the same table that refuses a configuration whose pins
 * do not match the board it names. Only what a picture and a sentence add
 * lives here, keyed by the server's `key`. A new board therefore needs one row
 * in host/lightshow/config.py, and an entry below only if it has a photograph.
 */
const WIZ_BOARD_ART = {
  'modell-2led-2relais-v1': {
    image: 'board-modell-2led-2relais-v1.png',
    blurb: 'Zwei LED-Ausgänge, zwei geschaltete Ausgänge, Pico gesockelt. '
      + 'Pegelwandler und Vorwiderstände sind drauf.',
  },
};

const wizExpert = () => ({
  key: FREE_BOARD,
  name: 'Experte — frei verdrahtet',
  blurb: 'Ein blanker Pico, alles selbst verdrahtet. Jeder GPIO steht zur '
    + 'Wahl, nichts ist vorbelegt, nichts wird geprüft außer den Regeln des '
    + 'Chips selbst.',
  sbus_pin: 5,
  led_pins: null,        // null heißt: keine Vorgabe
  relay_pins: null,
});

/* The bare Pico, drawn rather than photographed.
 *
 * The free build had a dashed box with "GP ?" in it, which said "no picture
 * here" where every other card says what you are choosing. A drawing does the
 * job a photograph would and is honest about being a drawing: castellated
 * edges, forty pins on 2.54 mm, the USB socket at one end, the RP2040 in the
 * middle, BOOTSEL at the other. Enough that the card is recognisable at a
 * glance, and no photograph to keep in step with a board revision.
 *
 * Drawn in millimetres times five, so the numbers are the datasheet's: the
 * board is 51 by 21, the pin rows sit 2.54 apart.
 */
const PICO_ART = (() => {
  const W = 255, H = 105, PITCH = 12.7, FIRST = 7;
  const holes = [];
  for (let i = 0; i < 20; i++) {
    const cx = FIRST + i * PITCH;
    for (const cy of [3, H - 3]) {
      // The castellation is a half hole in the edge: a plated ring with the
      // board colour inside, which is what you see on a real one.
      holes.push(`<circle cx="${cx}" cy="${cy}" r="4.6" fill="#c8a24a"/>`
               + `<circle cx="${cx}" cy="${cy}" r="2.6" fill="#0a2f1b"/>`);
    }
  }
  return `<svg class="wiz-pico" viewBox="-6 -4 ${W + 12} ${H + 8}"
      role="img" aria-label="Raspberry Pi Pico, blanke Platine">
    <rect x="0" y="0" width="${W}" height="${H}" rx="9"
      fill="#155232" stroke="#0d3a21" stroke-width="1.5"/>
    ${holes.join('')}
    <!-- The USB socket overhangs the short edge, which is how you tell which
         end is which from across the room. -->
    <rect x="-5" y="34" width="30" height="37" rx="4"
      fill="#c2c8d1" stroke="#8d949f" stroke-width="1.2"/>
    <rect x="1" y="41" width="17" height="23" rx="2" fill="#6f7681"/>
    <!-- RP2040, its flash, the button and the on-board lamp. -->
    <rect x="103" y="31" width="46" height="46" rx="4" fill="#15181d"/>
    <circle cx="112" cy="40" r="3" fill="#2c333d"/>
    <rect x="66" y="20" width="24" height="17" rx="2" fill="#15181d"/>
    <rect x="196" y="40" width="22" height="22" rx="3"
      fill="#e2e6eb" stroke="#9aa1ab" stroke-width="1.2"/>
    <circle cx="176" cy="24" r="4" fill="#3ddc84"/>
    <!-- The three debug pads on the far short edge. -->
    ${[38, 52, 66].map((cy) =>
      `<circle cx="243" cy="${cy}" r="4" fill="#c8a24a"/>`).join('')}
  </svg>`;
})();

/* One board as the step wants it: the server's pins plus the picture. */
function wizBoardCard(entry) {
  const art = WIZ_BOARD_ART[entry.key] || {};
  return {
    ...entry,
    image: art.image || null,
    blurb: art.blurb || `SBUS auf GP${entry.sbus_pin}, LED auf `
      + `GP${entry.led_pins.join('/GP')}, geschaltet auf `
      + `GP${entry.relay_pins.join('/GP')}.`,
    // Named the way the silkscreen names them, so somebody holding the board
    // can match the list against the copper without translating.
    ports: [
      ...entry.led_pins.map((pin, i) => `LED-${i + 1} · GP${pin}`),
      ...entry.relay_pins.map((pin, i) => `Relais ${i + 1} · GP${pin}`),
      `Receiver · GP${entry.sbus_pin}`,
      'UART-Debug · GP0/GP1',
    ],
  };
}

const wizBoards = () => BOARDS.map(wizBoardCard);

const wizBoard = () => wizBoards().find((entry) => entry.key === WIZ.board)
  || wizExpert();

/** true while a ready-made board decides the pins. */
const wizFixedPins = () => wizBoard().led_pins !== null;

const MAX_OUTPUTS = 8;      // one PIO state machine each
const MAX_SEGMENTS = 16;
const MAX_RELAYS = 8;
const MAX_OUTPUT_PIXELS = 256;

let WIZ = null;       // working state, null while the dialog is closed
let WIZ_BUS = null;   // last answer from /api/bus

/* GPIOs nothing else in the show has claimed. The model being edited does not
 * count against itself -- its own pins are still its own. */
const wizFreeGpio = () => {
  const used = new Set([0, 1]);                 // debug UART
  for (const model of (CONFIG ? CONFIG.models : [])) {
    if (WIZ && model.name === WIZ.editing) continue;
    const plane = model.plane;
    if (!plane) continue;
    used.add(plane.sbus_pin);
    (plane.outputs || []).forEach((output) => used.add(output.pin));
    (plane.relays || []).forEach((relay) => used.add(relay.pin));
  }
  if (WIZ) used.add(WIZ.sbus_pin);
  const free = [];
  for (let pin = 2; pin <= 22 && free.length < 24; pin++)
    if (!used.has(pin)) free.push(pin);
  return free;
};

/* The pins a ready-made board actually brings out for one purpose, minus the
 * ones this model has already claimed. On a free build every GPIO qualifies. */
function wizBoardPins(kind) {
  const board = wizBoard();
  const list = kind === 'led' ? board.led_pins : board.relay_pins;
  if (list === null) return wizFreeGpio();
  const taken = new Set(wizPinsInUse());
  return list.filter((pin) => !taken.has(pin));
}

/* A jack nobody drives yet, or the first one if all are taken. */
function wizFreePort() {
  const taken = new Set((CONFIG ? CONFIG.models : []).map((m) => m.tx_port));
  for (let id = 0; id < (CONFIG ? CONFIG.tx_ports.length : 0); id++)
    if (!taken.has(id)) return id;
  return 0;
}

/* Everybody else already on a jack, with the channel block each one holds.
 *
 * More than one model on one jack is a normal build: they share the
 * transmitter and take different eight-channel blocks out of the same frame.
 * What must not happen is two of them on the same channels, which the
 * configuration refuses -- so the wizard works it out first rather than letting
 * the save fail. */
function wizNeighbours(port = WIZ.tx_port, editing = WIZ && WIZ.editing) {
  return (CONFIG ? CONFIG.models : [])
    .filter((m) => m.tx_port === port && m.name !== editing)
    .map((m) => ({name: m.name, from: m.tx_offset, to: m.tx_offset + 8}));
}

/* The lowest place on this jack where eight free channels are left, or null if
 * the frame has no room for another model. */
function wizFreeOffset(port, nchan = WIZ.nchan, editing = WIZ && WIZ.editing) {
  const others = wizNeighbours(port, editing);
  for (let offset = 0; offset + 8 <= nchan; offset++) {
    if (!others.some((o) => offset < o.to && o.from < offset + 8)) return offset;
  }
  return null;
}

/* Who this model would sit on top of, if anybody. */
function wizBlockClash() {
  const mine = {from: WIZ.tx_offset, to: WIZ.tx_offset + 8};
  const hit = wizNeighbours().find((o) => mine.from < o.to && o.from < mine.to);
  return hit ? hit.name : null;
}

async function wizLoadBus() {
  const frame = WIZ.format === 'ppm' ? WIZ.frame_us : 7000;
  WIZ_BUS = await api(`/api/bus?frame_us=${frame}`);
  return WIZ_BUS;
}

/* How many channels are left on the transmitter, given where the light starts.
 * The bus needs eight of them, however many zones the model has. */
const wizFreeChannels = () => Math.max(0, WIZ.nchan - WIZ.tx_offset);

function wizMinimumFrame(nchan) {
  const table = WIZ_BUS && WIZ_BUS.ppm_frame_minimum;
  const value = table && table[String(nchan)];
  return value || 22500;
}

/* Every segment of every output, flattened -- the view the zones care about. */
const wizSegments = () => WIZ.outputs.flatMap(
  (output, oi) => output.segments.map((segment, si) => ({output, oi, segment, si})));

const wizSegmentCount = () => WIZ.outputs.reduce((n, o) => n + o.segments.length, 0);

/* How far a zone's virtual chain reaches: the furthest segment, not the sum.
 * Segments sharing an offset are mirrors of each other. */
const wizZonePixels = (zone) => wizSegments()
  .filter((e) => e.segment.zone === zone)
  .reduce((most, e) => Math.max(most, e.segment.offset + e.segment.count), 0);

/* ceil(log2(zones)), the address field the frame spends on the zone number.
 * Together with the relay bits it may not exceed four. */
const wizAddressBits = () => Math.ceil(Math.log2(Math.max(1, WIZ.zones)));

const wizPinsInUse = () => WIZ.outputs.map((o) => o.pin)
  .concat(WIZ.relays_cfg.map((r) => r.pin));

function wizNextPin(kind) {
  const free = wizBoardPins(kind);
  const taken = new Set(wizPinsInUse());
  return free.find((pin) => !taken.has(pin)) || free[0] || 2;
}

/* Carries a board choice into everything the board decides.
 *
 * Called when a card is clicked, not on every render: it moves pins about, and
 * doing that behind somebody's back while they edit would be rude. */
function wizApplyBoard() {
  const board = wizBoard();
  WIZ.sbus_pin = board.sbus_pin;
  if (board.led_pins === null) return;        // free build: nothing is decided

  // More outputs than the board has connectors cannot be wired at all.
  WIZ.outputs.length = Math.min(WIZ.outputs.length, board.led_pins.length);
  // Nothing configured yet: hand over the board's connectors straight away,
  // which is the whole point of asking first.
  if (!WIZ.outputs.length) {
    board.led_pins.forEach((pin, index) => {
      WIZ.outputs.push({
        name: `led${index + 1}`, pin, count: 30,
        segments: [{name: 'ganz', start: 0, count: 30,
                    zone: Math.min(index, WIZ.zones - 1), offset: 0,
                    reverse: false}],
      });
    });
  }
  WIZ.outputs.forEach((output, index) => { output.pin = board.led_pins[index]; });

  if (WIZ.relays > board.relay_pins.length) WIZ.relays = board.relay_pins.length;
  wizClampZones();
  WIZ.relays_cfg.forEach((relay, index) => { relay.pin = board.relay_pins[index]; });
}

/* ------------------------------------------------------------ open / close */

function wizBlank() {
  const port = wizFreePort();
  // Eight channels leaves 1..8 to the sticks, which is the usual split; on a
  // jack that already carries a model it is wherever the next free block is.
  const offset = wizFreeOffset(port, 16, null);
  return {
    step: 0,
    board: (BOARDS[0] || {key: FREE_BOARD}).key,   // a real board is the common case
    airframe: 'motor',      // what the preview draws the strips on
    editing: null,          // name of the model being reworked, or null
    name: '',
    tx_port: port,
    format: 'ppm',
    nchan: 16,
    frame_us: 35500,
    tx_offset: offset === null ? 8 : Math.max(offset, wizNeighbours(port, null).length ? offset : 8),
    zones: 2,
    relays: 0,               // bus relay slots, chosen in step 2
    outputs: [],
    relays_cfg: [],
    navs: [],
    sbus_pin: 5,
    max_brightness: 200,
    render_hz: 200,
  };
}

/* Reads an existing model back into the wizard's own shape. */
function wizFromModel(model) {
  const port = (CONFIG.tx_ports || []).find((p) => p.id === model.tx_port) || {};
  const plane = model.plane || {};
  return {
    step: 0,
    board: plane.board || FREE_BOARD,
    airframe: plane.airframe || 'motor',
    editing: model.name,
    name: model.name,
    tx_port: model.tx_port,
    format: port.format || 'ppm',
    nchan: port.nchan || 16,
    frame_us: port.frame_us || 35500,
    tx_offset: model.tx_offset,
    zones: Math.max(1, Math.floor(model.channels.length / 4)),
    relays: ((model.bus && model.bus.relays) || []).length,
    outputs: (plane.outputs || []).map((output) => ({
      name: output.name, pin: output.pin, count: output.count,
      segments: (output.segments || []).map((s) => ({...s})),
    })),
    relays_cfg: (plane.relays || []).map((relay) => ({...relay})),
    navs: (plane.nav_lights || []).map((nav) => ({...nav, color: [...nav.color]})),
    sbus_pin: plane.sbus_pin != null ? plane.sbus_pin : 5,
    max_brightness: plane.max_brightness != null ? plane.max_brightness : 200,
    render_hz: plane.render_hz != null ? plane.render_hz : 200,
  };
}

function wizOpen(name) {
  const existing = name
    ? (CONFIG.models || []).find((model) => model.name === name) : null;
  WIZ = existing ? wizFromModel(existing) : wizBlank();
  // A new model starts on the pre-selected board, so its pins are already
  // filled in when the LED step comes up -- no click needed to accept what is
  // already highlighted.
  if (!existing) wizApplyBoard();
  $('wiz-title').textContent = existing ? `Modell „${existing.name}“` : 'Neues Modell';
  wizLoadBus().then(() => {
    if (!existing) WIZ.frame_us = wizMinimumFrame(WIZ.nchan);
    wizRender();
  });
  $('wizard').showModal();
  wizRender();
}

function wizClose() {
  WIZ = null;
  $('wizard').close();
}

/* ------------------------------------------------------------------ step 0 */

/* The three shapes the preview can draw, with a plan view of each so the choice
 * is made by looking rather than by reading. Drawn here rather than fetched
 * from the renderer: this dialogue has no WebGL context, and a silhouette is
 * six path commands. The names have to match `AIRFRAMES` in airframe3d.js and
 * the table in config.py -- one word travels from here into show.yaml and out
 * again into the preview. */
const WIZ_AIRFRAMES = {
  motor: {
    name: 'Motorflugzeug', blurb: 'Rumpf, Tragfläche, Leitwerk, Propeller.',
    icon: `<svg class="wiz-kind-art" viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="11" r="8.5" fill="none" stroke-width="1.5"
        stroke-dasharray="3 3"/>
      <rect x="29" y="9" width="6" height="47" rx="3"/>
      <rect x="9" y="25" width="46" height="8" rx="4"/>
      <rect x="21" y="49" width="22" height="5.5" rx="2.75"/>
    </svg>`,
  },
  segler: {
    name: 'Segelflugzeug',
    blurb: 'Lange schmale Fläche, schlanker Rumpf, T-Leitwerk.',
    icon: `<svg class="wiz-kind-art" viewBox="0 0 64 64" aria-hidden="true">
      <rect x="30" y="8" width="4" height="49" rx="2"/>
      <ellipse cx="32" cy="15" rx="5" ry="7"/>
      <rect x="1" y="26" width="62" height="4" rx="2"/>
      <rect x="20" y="52" width="24" height="4" rx="2"/>
    </svg>`,
  },
  quad: {
    name: 'Quadrocopter',
    blurb: 'Vier Arme, vier Motoren — Streifen auf die Arme.',
    icon: `<svg class="wiz-kind-art" viewBox="0 0 64 64" aria-hidden="true">
      <path d="M24 24 L13 13 M40 24 L51 13 M24 40 L13 51 M40 40 L51 51"
        fill="none" stroke-width="4.5" stroke-linecap="round"/>
      <rect x="23" y="23" width="18" height="18" rx="5"/>
      <g fill="none" stroke-width="1.5" stroke-dasharray="3 3">
        <circle cx="13" cy="13" r="9"/><circle cx="51" cy="13" r="9"/>
        <circle cx="13" cy="51" r="9"/><circle cx="51" cy="51" r="9"/></g>
    </svg>`,
  },
};

/* Which board this aircraft is built on. Asked first because it answers, in
 * one click, questions three later steps would otherwise have to ask. */
function wizStepBoard() {
  const card = (entry, chosen) => `
    <button class="wiz-board ${chosen ? 'on' : ''}" data-wiz="board"
      data-key="${entry.key}" aria-pressed="${chosen}">
      ${entry.image
        ? `<img src="${entry.image}" alt="${esc(entry.name)}" loading="lazy">`
        : PICO_ART}
      <div class="wiz-board-text">
        <b>${esc(entry.name)}</b>
        <span>${esc(entry.blurb)}</span>
        ${entry.ports ? `<ul>${entry.ports.map((port) =>
          `<li>${esc(port)}</li>`).join('')}</ul>` : ''}
      </div>
    </button>`;

  const kind = (key, entry) => `
    <button class="wiz-board wiz-kind ${WIZ.airframe === key ? 'on' : ''}"
      data-wiz="airframe" data-key="${key}"
      aria-pressed="${WIZ.airframe === key}">
      ${entry.icon}
      <div class="wiz-board-text">
        <b>${esc(entry.name)}</b>
        <span>${esc(entry.blurb)}</span>
      </div>
    </button>`;

  return `
    <p class="muted" style="margin:0 0 14px">Was für ein Modell ist das? Danach
      richtet sich allein die <b>Vorschau</b>: worauf die Streifen gezeichnet
      werden und wie das Flugzeug im Modellbild aussieht. An Bord ändert es
      nichts — der Generator liest es nicht, über die Funkstrecke geht es nie.</p>

    <div class="wiz-boards">
      ${Object.entries(WIZ_AIRFRAMES).map(([key, entry]) => kind(key, entry)).join('')}
    </div>

    <h3 class="section">Worauf sitzt der Pico?</h3>
    <p class="muted" style="margin:0 0 14px">Eine fertige Platine hat ihre
      Anschlüsse im Kupfer — dann füllt der Wizard die GPIOs ein, statt danach zu
      fragen, und die späteren Schritte bieten nur noch an, was die Platine
      hergibt.</p>

    <div class="wiz-boards">
      ${wizBoards().map((entry) => card(entry, WIZ.board === entry.key)).join('')}
      ${card(wizExpert(), WIZ.board === FREE_BOARD)}
    </div>

    ${wizFixedPins() ? `<div class="note ok" style="margin-top:14px">
      <b>${esc(wizBoard().name)}</b> ist gewählt. SBUS liegt auf
      GP${wizBoard().sbus_pin}, die LED-Ausgänge auf
      GP${wizBoard().led_pins.join(' und GP')}, die geschalteten Ausgänge auf
      GP${wizBoard().relay_pins.join(' und GP')} — diese Felder sind in den
      folgenden Schritten festgelegt.
    </div>` : `<div class="note" style="margin-top:14px">
      <b>Frei verdrahtet.</b> Jeder GPIO steht zur Wahl. Geprüft wird nur, was
      der Chip selbst verlangt: SBUS nur auf einem Pin, den uart1 erreicht,
      GPIO 0 und 1 bleiben der Konsole, und kein Pin zweimal.
    </div>`}`;
}

function wizStepRadio() {
  const cueRate = (WIZ.format === 'ppm' ? WIZ.frame_us : 7000) / 1000;
  const free = wizFreeChannels();
  const minimum = wizMinimumFrame(WIZ.nchan);
  const tooShort = WIZ.format === 'ppm' && WIZ.frame_us < minimum;

  return `
    <p class="muted" style="margin:0 0 14px">Was der Trainer-Eingang Deines Senders
      entgegennimmt. Davon hängt alles Weitere ab: wie viele Kanäle es gibt, wie lang
      ein Rahmen wird und wie schnell ein Cue-Wechsel ankommt.</p>

    <div class="fgrid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">
      <div><label class="lbl">Name des Modells</label>
        <input type="text" id="wiz-name" value="${esc(WIZ.name)}"
          placeholder="z. B. eule" style="width:100%"></div>
      <div><label class="lbl">Sender-Buchse</label>
        <select id="wiz-port" style="width:100%">
          ${(CONFIG ? CONFIG.tx_ports : []).map((port) => {
            // Who is already there, not "taken": a second model on the same
            // jack is a build, not a mistake. What it has to avoid is their
            // channel blocks, and that is what the offset below is for. This
            // model itself is counted by where the wizard currently points --
            // not by where the file still has it, which is a save behind.
            const here = wizNeighbours(port.id).map((other) => other.name);
            const mine = WIZ.tx_port === port.id;
            // A jack nothing sits on has no format worth mentioning: whatever
            // stands there is a leftover from the model that used to be there,
            // and the next one to land writes its own. So the signal shape is
            // only shown where somebody is actually using it -- for this model
            // as the wizard would write it, for the others as the file has it.
            const shape = (format, nchan) => format === 'off' ? ''
              : format === 'sbus' ? 'SBUS' : `PPM ${nchan} Kanäle`;
            const who = [mine ? 'dieses Modell' : '', here.join(', ')].filter(Boolean);
            const state = who.length
              ? [who.join(' + '), mine ? shape(WIZ.format, WIZ.nchan)
                                       : shape(port.format, port.nchan)]
                  .filter(Boolean).join(' · ')
              : 'frei';
            return `<option value="${port.id}" ${mine ? 'selected' : ''}
              >Buchse ${port.id + 1} · GP${portGpio(port.id)} — ${esc(state)}</option>`;
          }).join('')}
        </select></div>
    </div>

    <h3 class="section">Signalform</h3>
    <div class="fgrid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">
      <div><label class="lbl">Format</label>
        <select id="wiz-format" style="width:100%">
          <option value="ppm" ${WIZ.format === 'ppm' ? 'selected' : ''}>PPM (Klinke)</option>
          <option value="sbus" ${WIZ.format === 'sbus' ? 'selected' : ''}
            >SBUS (seriell) — experimentell</option>
        </select></div>
      <div><label class="lbl">Kanäle</label>
        <select id="wiz-nchan" style="width:100%">
          ${[8, 10, 12, 14, 16].map((n) =>
            `<option value="${n}" ${WIZ.nchan === n ? 'selected' : ''}>${n}</option>`).join('')}
        </select></div>
      <!-- Spelled out: the label is set in capitals, and a capital µ reads as M. -->
      <div><label class="lbl">Rahmenlänge in Mikrosekunden</label>
        <!-- SBUS has one frame rate, so the field would be a setting that
             changes nothing. It shows what will actually be written. -->
        <input type="number" id="wiz-frame" min="4000" max="60000" step="100"
          value="${WIZ.format === 'ppm' ? WIZ.frame_us : 7000}"
          class="${tooShort ? 'err' : ''}" style="width:100%"
          ${WIZ.format === 'ppm' ? ''
            : 'disabled title="SBUS sendet alle 7 ms, das ist nicht einstellbar"'}></div>
      <div><label class="lbl">Licht beginnt bei Kanal</label>
        <input type="number" id="wiz-offset" min="0" max="15"
          value="${WIZ.tx_offset}" style="width:100%"></div>
    </div>

    ${tooShort ? `<div class="note warn" style="margin-top:12px">
      ${WIZ.nchan} Kanäle brauchen mindestens <b>${minimum} µs</b>. Kürzer nimmt die
      Bordfirmware den Rahmen nicht an.</div>` : ''}

    ${WIZ.format === 'sbus' ? `<div class="note warn" style="margin-top:12px">
      <b>SBUS in den Sender ist experimentell.</b> Die Bodenstation kann es
      erzeugen, aber diesen Weg ist noch nie ein Rahmen wirklich gegangen:
      gemessen und geflogen wurde ausschließlich PPM über die Klinke.
      <ul style="margin:6px 0 0;padding-left:18px">
        <li>Die Trainer-Klinke reicht dafür in der Regel nicht — sie nimmt meist
          nur CPPM entgegen. Ein serieller Trainer-Eingang ist, wenn überhaupt,
          ein anderer Anschluss und heißt je nach Hersteller anders. Ob Dein
          Sender ihn hat, steht in seinem Handbuch.</li>
        <li>Der Gewinn wäre groß: 7 ms Rahmen statt 35,5, also
          ${(7 * WIZ.zones).toFixed(0)} ms statt
          ${(35.5 * WIZ.zones).toFixed(0)} ms Wartezeit bei ${WIZ.zones} Zonen —
          und die PPM-Dekodierung im Sender, die je nach Gerät Rahmen kosten
          kann, entfiele.</li>
      </ul>
      Wer es probiert: erst am Boden im Kanalmonitor prüfen, dann fliegen.
      Der Hintergrund steht in <i>docs/bus-modus.md</i>, das Konkrete zum
      eigenen Sender in <i>docs/sender-setup.md</i>.
    </div>` : ''}

    ${wizNeighbours().length ? `<div class="note" style="margin-top:12px">
      Auf dieser Buchse sitzt auch
      <b>${esc(wizNeighbours().map((other) => other.name).join(', '))}</b>.
      Format, Kanalzahl und Rahmenlänge gehören der <i>Buchse</i> — es ist ein
      Signal aus einer Klinke, und was hier steht, gilt für alle daran. Getrennt
      ist nur der Kanalblock: ${esc(wizNeighbours().map(
        (other) => `${other.name} auf ${other.from + 1}–${other.to}`).join(', '))}.
    </div>` : ''}

    <div class="note" style="margin-top:14px">
      <b>${free}</b> Kanäle stehen dem Licht zur Verfügung (${WIZ.tx_offset + 1}–${WIZ.nchan}),
      ein Rahmen dauert <b>${cueRate.toFixed(1)} ms</b>. Belegt werden davon acht:
      so viele trägt der codierte Rahmen, unabhängig von der Zahl der Zonen.
      ${WIZ.tx_offset > 0 ? `Die Kanäle 1–${WIZ.tx_offset} bleiben den Knüppeln.` :
        'Achtung: das Licht beginnt bei Kanal 1, es bleibt nichts für Knüppel und Schalter.'}
    </div>

    <h3 class="section">Bordelektronik</h3>
    <p class="muted" style="margin:0 0 12px;font-size:12.5px">Drei Dinge, die der
      Pico im Rumpf wissen muss. Sie werden in seine <code>config.h</code>
      geschrieben, gelten also erst nach dem nächsten Aufspielen.</p>
    <div class="fgrid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">
      <div><label class="lbl">SBUS-Eingang (GPIO)</label>
        <input type="number" id="wiz-sbus" min="0" max="28"
          value="${WIZ.sbus_pin}" style="width:100%"
          ${wizFixedPins() ? 'disabled title="Von der Platine vorgegeben"' : ''}>
        <span class="wiz-hint">Wo das SBUS-Kabel des Empfängers ankommt.
          ${wizFixedPins() ? `Auf ${esc(wizBoard().name)} fest verdrahtet.`
            : 'Nur wenige Pins können das: die Firmware liest über uart1, und '
              + 'dessen Empfangsleitung kommt nur an GP5, GP9 und GP21 heraus.'}
        </span></div>
      <div><label class="lbl">Helligkeitsdeckel</label>
        <input type="number" id="wiz-maxbright" min="1" max="255"
          value="${WIZ.max_brightness}" style="width:100%">
        <span class="wiz-hint">Obergrenze für alles, 1–255. Begrenzt den
          Spitzenstrom und die Blendwirkung für den Piloten. Ein 30er Streifen
          zieht auf Weiß und voll 1,8 A; mit 200 und üblichen Farben sind es
          rund 0,5 A.</span></div>
      <div><label class="lbl">Renderrate (Hz)</label>
        <input type="number" id="wiz-renderhz" min="30" max="1000"
          value="${WIZ.render_hz}" style="width:100%">
        <span class="wiz-hint">Wie oft der Pico die Streifen neu rechnet und
          ausgibt, 30–1000. Die Effekte laufen damit an Bord, unabhängig von der
          Funkstrecke — deshalb sind Strobes flüssig, obwohl über die Luft nur
          rund 28 Rahmen je Sekunde kommen. 200 ist reichlich.</span></div>
    </div>

    <div class="note" style="margin-top:14px">Der Streifen braucht ein eigenes
      UBEC am Flugakku, nicht das BEC des Empfängers — und einen Pegelwandler auf
      5 V vor dem Dateneingang.
      ${wizFixedPins() ? `Auf ${esc(wizBoard().name)} ist der schon drauf.`
        : 'Beim freien Aufbau kommt beides dazu; siehe <i>hardware/README.md</i>.'}
    </div>`;
}

/* ------------------------------------------------------------------ step 1 */

function wizStepZones() {
  const board = wizBoard();
  const all = (WIZ_BUS && WIZ_BUS.ports && WIZ_BUS.ports.asked)
    ? WIZ_BUS.ports.asked.combinations : [];
  // A bit nothing can be wired to is not a choice. The board caps the columns
  // just as the payload caps them from the other side.
  const table = board.relay_pins === null ? all
    : all.filter((entry) => entry.relays <= board.relay_pins.length);
  const limit = WIZ_BUS ? WIZ_BUS.limit_ms : 150;

  const matrix = busMatrix(table, WIZ.zones, WIZ.relays,
    (zones, relays) => `data-wiz="combo" data-zones="${zones}" data-relays="${relays}"`);

  return `
    <p class="muted" style="margin:0 0 14px">Eine Zone ist ein Stück Beleuchtung, das
      gemeinsam geschaltet wird — etwa eine Tragfläche. Jede Zone hat ihren eigenen
      Effekt, ihre eigene Farbe, Helligkeit und Tempo.</p>

    <h3 class="section">Zonen und Bus-Relais wählen</h3>
    <p class="muted" style="margin:0 0 10px;font-size:12.5px">
      Die acht Kanäle tragen einen codierten Rahmen, der die Zonen reihum bedient.
      Jede Kachel ist eine mögliche Aufteilung samt der Wartezeit, bis dieselbe Zone
      wieder an der Reihe ist — das ist der Preis für mehr Zonen.
      Relais <b>am Bus</b> werden direkt geschaltet und kosten Nutzbits, daher der
      Abtausch nach rechts. Relais, die einem Effekt folgen, kosten nichts und werden
      im Schritt <i>Relais</i> eingerichtet.
      Blass hinterlegt heißt: langsamer als die eingestellte Grenze von ${limit} ms.
      ${board.relay_pins ? `<br><b>${esc(board.name)}</b> hat
        ${board.relay_pins.length} geschaltete Ausgänge — mehr Relais stehen
        deshalb nicht zur Wahl, so viel Budget auch übrig wäre.` : ''}
    </p>
    ${matrix}`;
}

/* ------------------------------------------------------------------ step 2 */

/* Two questions, in the order the soldering iron asks them: which GPIOs have a
 * chain on them, and only then how each chain is divided between the zones.
 * They used to be one table, which forced a chain to be exactly one zone. */
function wizStepOutputs() {
  const board = wizBoard();
  const fixed = wizFixedPins();
  const ledPins = wizBoardPins('led');
  const roomForOutputs = fixed ? board.led_pins.length : MAX_OUTPUTS;
  const total = wizSegmentCount();

  const cards = WIZ.outputs.map((output, oi) => {
    const rows = output.segments.map((segment, si) => `
      <tr>
        <td><input type="text" value="${esc(segment.name)}" style="width:110px"
          data-wiz="seg" data-o="${oi}" data-i="${si}" data-key="name"></td>
        <td><input type="number" min="0" max="255" value="${segment.start}" style="width:64px"
          data-wiz="seg" data-o="${oi}" data-i="${si}" data-key="start"></td>
        <td><input type="number" min="1" max="256" value="${segment.count}" style="width:64px"
          data-wiz="seg" data-o="${oi}" data-i="${si}" data-key="count"></td>
        <td><select style="width:88px" data-wiz="seg" data-o="${oi}" data-i="${si}" data-key="zone">
          ${Array.from({length: WIZ.zones}, (_, zone) =>
            `<option value="${zone}" ${segment.zone === zone ? 'selected' : ''}
              >Zone ${zone + 1}</option>`).join('')}
        </select></td>
        <td><input type="number" min="0" max="255" value="${segment.offset}" style="width:64px"
          data-wiz="seg" data-o="${oi}" data-i="${si}" data-key="offset"></td>
        <td style="text-align:center"><input type="checkbox" ${segment.reverse ? 'checked' : ''}
          data-wiz="seg" data-o="${oi}" data-i="${si}" data-key="reverse"></td>
        <td class="nowrap">
          <button class="tiny" data-wiz="seg-split" data-o="${oi}" data-i="${si}"
            title="Diesen Abschnitt in der Mitte teilen">Teilen</button>
          <button class="tiny danger" data-wiz="seg-del" data-o="${oi}" data-i="${si}"
            title="Abschnitt entfernen">Entfernen</button></td>
      </tr>`).join('');

    return `
      <div class="wiz-card">
        <div class="row" style="gap:10px;align-items:flex-end;flex-wrap:wrap">
          <div><label class="lbl">Name</label>
            <input type="text" value="${esc(output.name)}" style="width:150px"
              data-wiz="out" data-i="${oi}" data-key="name"></div>
          <div><label class="lbl">GPIO</label>
            <select style="width:88px" data-wiz="out" data-i="${oi}" data-key="pin"
              ${fixed ? 'disabled title="Von der Platine vorgegeben"' : ''}>
              ${ledPins.concat([output.pin]).filter((v, i, a) => a.indexOf(v) === i)
                .sort((a, b) => a - b).map((pin) =>
                  `<option value="${pin}" ${output.pin === pin ? 'selected' : ''}
                    >GP${pin}</option>`).join('')}
            </select></div>
          <div><label class="lbl">Pixel am Streifen</label>
            <input type="number" min="1" max="${MAX_OUTPUT_PIXELS}" value="${output.count}"
              style="width:92px" data-wiz="out" data-i="${oi}" data-key="count"></div>
          <span class="grow"></span>
          <button class="tiny danger" data-wiz="out-del" data-i="${oi}"
            title="Diesen Ausgang samt Abschnitten entfernen">Ausgang entfernen</button>
        </div>

        <div class="wiz-sub">Abschnitte — welches Stück dieser Kette zu welcher Zone gehört</div>
        <div class="tablewrap"><table class="form">
          <thead><tr><th>Name</th><th>ab Pixel</th><th>Länge</th><th>Zone</th>
            <th>Offset</th><th>rückwärts</th><th></th></tr></thead>
          <tbody>${rows || `<tr><td colspan="7" class="dim">noch nicht unterteilt</td></tr>`}</tbody>
        </table></div>
        <div class="row" style="margin-top:8px;gap:10px">
          <button class="tiny" data-wiz="seg-add" data-i="${oi}"
            id="wiz-segadd-${oi}">＋ Abschnitt</button>
          <span class="dim" id="wiz-tally-${oi}" style="font-size:11.5px"></span>
        </div>
      </div>`;
  }).join('');

  return `
    <p class="muted" style="margin:0 0 14px">Zuerst die Ausgänge: an welchen GPIOs
      hängt tatsächlich ein Streifen, und wie lang ist er. Danach wird jeder Streifen
      unterteilt — ein Abschnitt ist ein Stück der Kette und gehört zu genau einer
      Zone. So kann ein einziger Streifen vorn Rumpf und hinten Leitwerk sein.</p>

    ${cards || '<div class="note">Noch kein Ausgang. Ein Modell ohne LED-Streifen ist erlaubt — dann bleibt hier alles leer.</div>'}

    <div class="row" style="margin-top:12px;gap:10px">
      <button data-wiz="out-add"
        ${WIZ.outputs.length >= roomForOutputs ? 'disabled' : ''}
        title="${WIZ.outputs.length >= roomForOutputs && fixed
          ? `${esc(board.name)} hat ${board.led_pins.length} LED-Anschlüsse`
          : 'Eine weitere WS2812-Kette'}">＋ LED-Ausgang</button>
      <span class="dim" id="wiz-outsum" style="font-size:12px"></span>
    </div>

    <div class="note" style="margin-top:14px">Der <b>Offset</b> ist die Position im
      Lauflicht der Zone: zwei Abschnitte mit demselben Offset spiegeln sich,
      hintereinander gesetzte ergeben eine lange Kette, über die ein Lauflicht
      durchläuft.</div>

    <h3 class="section">Was jede Zone dann treibt</h3>
    <ul class="wiz-list" id="wiz-perzone"></ul>`;
}

/* Everything on the LED step that follows a number somebody is typing.
 *
 * Re-rendering on each keystroke would tear the field out from under the
 * cursor, so the counts, the summary and the buttons that depend on them are
 * written back in place instead. */
function wizRefreshOutputs() {
  const total = wizSegmentCount();

  WIZ.outputs.forEach((output, oi) => {
    const claimed = output.segments.reduce(
      (most, s) => Math.max(most, s.start + s.count), 0);
    const spare = output.count - claimed;

    const tally = document.getElementById(`wiz-tally-${oi}`);
    if (tally) {
      tally.innerHTML = `${claimed} von ${output.count} Pixeln vergeben` + (
        spare > 0 ? `, ${spare} frei`
        : spare < 0 ? ', <b class="warn-text">zu viel</b>' : '');
    }

    const add = document.getElementById(`wiz-segadd-${oi}`);
    if (add) {
      add.disabled = !(spare > 0 && total < MAX_SEGMENTS);
      add.title = spare > 0 ? 'Einen Abschnitt auf die freien Pixel legen'
        : 'Kein freies Stück mehr — einen vorhandenen Abschnitt teilen';
    }

    output.segments.forEach((segment, si) => {
      const split = document.querySelector(
        `button[data-wiz="seg-split"][data-o="${oi}"][data-i="${si}"]`);
      if (split) split.disabled = !(segment.count > 1 && total < MAX_SEGMENTS);
    });
  });

  const summary = document.getElementById('wiz-outsum');
  if (summary) {
    const board = wizBoard();
    const room = wizFixedPins() ? board.led_pins.length : MAX_OUTPUTS;
    summary.textContent = `${WIZ.outputs.length}/${room} Ausgänge, `
      + `${total}/${MAX_SEGMENTS} Abschnitte — `
      + (wizFixedPins() ? `so viele LED-Anschlüsse hat ${board.name}.`
         : 'mehr Ausgänge gehen nicht, es gibt acht PIO-Zustandsmaschinen.');
  }

  const perZone = document.getElementById('wiz-perzone');
  if (perZone) {
    perZone.innerHTML = Array.from({length: WIZ.zones}, (_, zone) => {
      const mine = wizSegments().filter((e) => e.segment.zone === zone);
      return `<li>Zone ${zone + 1}: ${mine.length
        ? `${mine.map((e) => `${esc(e.segment.name)} <span class="dim">an `
            + `${esc(e.output.name)}</span>`).join(', ')}`
          + ` — ${wizZonePixels(zone)} Pixel lang`
        : '<span class="warn-text">noch nichts zugeordnet</span>'}</li>`;
    }).join('');
  }
}

/* ------------------------------------------------------------------ step 3 */

/* A relay is switched over the bus and nowhere else: one bit in every frame,
 * one control change to drive it with. It hangs off no zone, follows no effect
 * and has no threshold -- there is nothing left to choose but where it is
 * wired and how fast it may switch.
 *
 * How many there may be is decided in the Zonen step, because the bits come out
 * of the same payload as the zone address. This step can only fill them. */
function wizStepRelays() {
  const fixed = wizFixedPins();
  const free = wizBoardPins('relay');
  const spare = WIZ.relays - WIZ.relays_cfg.length;

  const rows = WIZ.relays_cfg.map((relay, index) => `
    <tr>
      <td class="dim n">Bit ${index}</td>
      <td><input type="text" value="${esc(relay.name)}" style="width:150px"
        data-wiz="relay" data-i="${index}" data-key="name"></td>
      <td><select style="width:88px" data-wiz="relay" data-i="${index}" data-key="pin"
        ${fixed ? 'title="Von der Platine vorgegeben"' : ''}>
        ${free.concat([relay.pin]).filter((v, i, a) => a.indexOf(v) === i)
          .sort((a, b) => a - b).map((pin) =>
            `<option value="${pin}" ${relay.pin === pin ? 'selected' : ''}>GP${pin}</option>`).join('')}
      </select></td>
      <td style="text-align:center"><input type="checkbox" ${relay.active_low ? 'checked' : ''}
        data-wiz="relay" data-i="${index}" data-key="active_low"></td>
      <td><input type="number" min="0" max="5000" step="50" value="${relay.min_on_ms}"
        style="width:76px" data-wiz="relay" data-i="${index}" data-key="min_on_ms"></td>
      <td><input type="number" min="0" max="5000" step="50" value="${relay.min_off_ms}"
        style="width:76px" data-wiz="relay" data-i="${index}" data-key="min_off_ms"></td>
      <td><button class="tiny danger" data-wiz="relay-del" data-i="${index}"
        title="Relais entfernen">Entfernen</button></td>
    </tr>`).join('');

  return `
    <p class="muted" style="margin:0 0 14px">Ein Relais schaltet etwas, das keine LED ist —
      Scheinwerfer, Rauch, Landelicht. Es bekommt ein eigenes Bit im Rahmen, das in
      <b>jedem</b> Rahmen mitfährt, und einen eigenen Control-Change: ab 64 an, darunter
      aus. Es hängt an keiner Zone und folgt keinem Effekt.</p>

    ${WIZ.relays ? `<div class="note" style="margin-bottom:12px">
      Im Schritt <i>Zonen</i> sind <b>${WIZ.relays}</b> Bits reserviert,
      <b>${WIZ.relays_cfg.length}</b> davon eingerichtet${spare > 0
        ? `, ${spare} noch frei` : ' — alle vergeben'}.
      Mehr gehen nur, wenn dort weniger Zonen gewählt werden.
    </div>` : `<div class="note warn" style="margin-bottom:12px">
      Im Schritt <i>Zonen</i> ist <b>kein</b> Bit für Relais reserviert, deshalb geht
      hier keins. ${WIZ.zones} Zonen brauchen ${wizAddressBits()} Adressbits, und
      Adresse plus Relais dürfen zusammen vier nicht überschreiten.
    </div>`}

    <div class="tablewrap"><table class="form">
      <thead><tr><th></th><th>Name</th><th>GPIO</th><th>invertiert</th>
        <th>min. an (ms)</th><th>min. aus (ms)</th><th></th></tr></thead>
      <tbody>${rows || '<tr><td colspan="7" class="dim">noch keine Relais</td></tr>'}</tbody>
    </table></div>
    <div class="row" style="margin-top:10px;gap:10px">
      <button data-wiz="relay-add" ${spare > 0 ? '' : 'disabled'}
        title="${spare > 0 ? 'Belegt das nächste freie Bit'
          : 'Alle im Schritt Zonen reservierten Bits sind vergeben'}"
        >＋ Relais</button>
      <span class="dim" style="font-size:12px">${WIZ.relays_cfg.length}/${WIZ.relays}</span>
    </div>

    <div class="note" style="margin-top:14px">
      <b>invertiert</b> für fertige Relaismodule, die bei LOW schalten.
      <b>min. an/aus</b> schützt ein mechanisches Relais vor dem Klappern — 0 für
      MOSFETs, etwa 200 ms für ein echtes Relais. Die Reihenfolge oben ist die
      Bitreihenfolge auf der Leitung; Verschieben vertauscht die Geräte.
    </div>`;
}

/* ------------------------------------------------------------------ step 4 */

/* The three lights an aircraft has by convention. The colours are the whole
 * point of a navigation light -- red to port, green to starboard, white aft --
 * so they come ready-made and only the place has to be said. */
const NAV_TEMPLATES = [
  {what: 'links', side: 'Backbord', color: [255, 0, 0]},
  {what: 'rechts', side: 'Steuerbord', color: [0, 255, 0]},
  {what: 'hinten', side: 'Heck', color: [255, 255, 255]},
];

const navTemplate = (colour) => NAV_TEMPLATES.find(
  (entry) => entry.color.every((value, at) => value === colour[at]));

/* Navigation lights sit on a chain, not on a zone: it is a lamp at a wingtip,
 * and which zone happens to cover that pixel is irrelevant to it. */
function wizStepNav() {
  const room = WIZ.outputs.length > 0 && WIZ.navs.length < 16;
  // Only what is not there yet, so the button stays useful after one was
  // deleted instead of being locked out by the other two.
  const missing = NAV_TEMPLATES.filter(
    (entry) => !WIZ.navs.some((nav) => navTemplate(nav.color) === entry));
  const rows = WIZ.navs.map((nav, index) => {
    const output = WIZ.outputs[nav.output];
    const limit = output ? output.count - 1 : 0;
    const template = navTemplate(nav.color);
    return `
      <tr>
        <td>${template
          ? `<b>${template.side}</b> <span class="dim">· ${template.what}</span>`
          : '<span class="dim">eigene Farbe</span>'}</td>
        <td><select style="width:170px" data-wiz="nav" data-i="${index}" data-key="output">
          ${WIZ.outputs.map((entry, oi) =>
            `<option value="${oi}" ${nav.output === oi ? 'selected' : ''}
              >${esc(entry.name)} · GP${entry.pin}</option>`).join('')}
        </select></td>
        <td><input type="number" min="0" max="${limit}" value="${nav.index}" style="width:80px"
          class="${output && nav.index > limit ? 'err' : ''}"
          data-wiz="nav" data-i="${index}" data-key="index"></td>
        <td class="dim" style="font-size:11.5px">${output
          ? `von ${output.count} Pixeln` : 'Ausgang fehlt'}</td>
        <td><input type="color" value="${rgbHex(nav.color)}"
          data-wiz="nav-colour" data-i="${index}"></td>
        <td><button class="tiny danger" data-wiz="nav-del" data-i="${index}"
          title="Positionslicht entfernen">Entfernen</button></td>
      </tr>`;
  }).join('');

  return `
    <p class="muted" style="margin:0 0 14px">Positionslichter liegen über jedem Effekt
      und lassen sich nicht abschalten — rot links, grün rechts, weiß nach hinten.
      Sie sitzen auf einem Ausgang, nicht auf einer Zone: der Pixel wird über die
      ganze Kette gezählt, unabhängig davon, welcher Abschnitt ihn gerade bespielt.</p>

    ${WIZ.outputs.length ? '' : `<div class="note warn" style="margin-bottom:12px">
      Erst ein LED-Ausgang, dann ein Positionslicht darauf.</div>`}

    <div class="tablewrap"><table class="form">
      <thead><tr><th>Position</th><th>Ausgang</th><th>Pixel</th><th></th>
        <th>Farbe</th><th></th></tr></thead>
      <tbody>${rows || '<tr><td colspan="6" class="dim">noch keine Positionslichter</td></tr>'}</tbody>
    </table></div>

    <div class="row" style="margin-top:10px;gap:8px;flex-wrap:wrap">
      <button data-wiz="nav-standard" ${room && missing.length ? '' : 'disabled'}
        title="${missing.length
          ? `Legt ${missing.map((entry) => entry.side).join(', ')} an`
          : 'Alle drei sind schon da'}"
        >＋ Die drei Standardlichter</button>
      ${NAV_TEMPLATES.map((entry, index) => `
        <button class="tiny" data-wiz="nav-add" data-t="${index}" ${room ? '' : 'disabled'}>
          <span class="nav-dot" style="background:${rgbHex(entry.color)}"></span>
          ${entry.side}</button>`).join('')}
      <button class="tiny quiet" data-wiz="nav-add" data-t="-1" ${room ? '' : 'disabled'}
        title="Eigene Farbe, etwa ein Blitzlicht">＋ eigenes</button>
      <span class="grow"></span>
      <span class="dim" style="font-size:12px">${WIZ.navs.length}/16</span>
    </div>

    <div class="note" style="margin-top:14px">Angeben musst Du nur noch, an welchem
      Ausgang das Licht sitzt und der wievielte Pixel es ist — die Farbe bringt jedes
      der drei mit. Ändern lässt sie sich trotzdem.</div>`;
}

/* ----------------------------------------------------------------- render */

const WIZ_RENDERERS = [wizStepBoard, wizStepRadio, wizStepZones, wizStepOutputs,
                       wizStepRelays, wizStepNav];

function wizRender() {
  if (!WIZ) return;
  $('wiz-body').innerHTML = WIZ_RENDERERS[WIZ.step]();
  // The LED step leaves its counts empty in the markup; they are filled by the
  // same code that keeps them current while numbers are typed.
  if (WIZ.step === 3) wizRefreshOutputs();

  // Every step is reachable at any time -- reworking an aircraft usually means
  // going straight to the one thing that changed. A step that has a problem
  // says so on its tab rather than blocking the way there.
  $('wiz-steps').innerHTML = WIZ_STEPS.map((label, index) => {
    const problem = wizProblem(index);
    return `<span class="wiz-step ${index === WIZ.step ? 'on' : ''}
      ${problem ? 'bad' : 'done'}" data-wiz="step" data-step="${index}"
      title="${problem ? esc(problem) : 'fertig'}"
      >${index + 1}. ${label}${problem ? ' ⚠' : ''}</span>`;
  }).join('');

  const last = WIZ.step === WIZ_STEPS.length - 1;
  $('wiz-back').disabled = WIZ.step === 0;
  $('wiz-next').classList.toggle('hidden', last);
  // A model being reworked is already complete, so the change can be taken from
  // wherever it was made -- coming to change one number and then paging through
  // four more steps to find the button is work that answers nothing. A new
  // model still has to reach the end, because it is not finished before then.
  $('wiz-create').classList.toggle('hidden', !last && !WIZ.editing);
  // Until the last step, going on is the ordinary next move and taking it is
  // the exception; two primary buttons side by side would say neither.
  $('wiz-create').classList.toggle('primary', last);
  $('wiz-create').textContent = WIZ.editing ? 'Übernehmen' : 'Modell anlegen';
  wizRefreshFooter();
}

/* Only the footer, so typing in a text field does not lose the caret. */
function wizRefreshFooter() {
  const here = wizProblem(WIZ.step);
  const anywhere = wizFirstProblem();
  $('wiz-next').disabled = !!here;
  $('wiz-create').disabled = !!anywhere;
  const note = here || (anywhere
    ? `${anywhere[0] + 1}. ${WIZ_STEPS[anywhere[0]]}: ${anywhere[1]}` : '');
  $('wiz-note').textContent = note;
  $('wiz-note').classList.toggle('hidden', !note);
}

/* The earliest step that is not finished, as [index, sentence]. */
function wizFirstProblem() {
  for (let step = 0; step < WIZ_STEPS.length; step++) {
    const problem = wizProblem(step);
    if (problem) return [step, problem];
  }
  return null;
}

/* What stops one step from being finished, in one sentence. */
function wizProblem(step) {
  if (step === 1) {
    const name = WIZ.name.trim();
    if (!name) return 'Das Modell braucht einen Namen.';
    if (!/^[a-z0-9_]+$/.test(name))
      return 'Nur Kleinbuchstaben, Ziffern und Unterstrich — der Name wird ein Dateiname.';
    if ((CONFIG ? CONFIG.models : []).some(
        (m) => m.name === name && m.name !== WIZ.editing))
      return `Ein Modell '${name}' gibt es schon.`;
    if (WIZ.format === 'ppm' && WIZ.frame_us < wizMinimumFrame(WIZ.nchan))
      return `Der Rahmen ist zu kurz für ${WIZ.nchan} Kanäle.`;
    if (wizFreeChannels() < 8)
      return 'Der codierte Rahmen braucht acht freie Kanäle.';
    const clash = wizBlockClash();
    if (clash) {
      const free = wizFreeOffset(WIZ.tx_port);
      return `Die Kanäle ${WIZ.tx_offset + 1}–${WIZ.tx_offset + 8} gehören auf `
        + `dieser Buchse schon '${clash}'.`
        + (free === null ? ' Auf dieser Buchse ist kein Block mehr frei.'
                         : ` Frei ab Kanal ${free + 1}.`);
    }
  }

  if (step === 2) {
    if (WIZ.zones < 1 || WIZ.zones > 8) return 'Zwischen einer und acht Zonen.';
  }

  if (step === 3) {
    for (const output of WIZ.outputs) {
      if (!output.count) return `'${output.name}' hat keine Pixel.`;
      const sorted = [...output.segments].sort((a, b) => a.start - b.start);
      for (let i = 0; i < sorted.length; i++) {
        if (sorted[i].start + sorted[i].count > output.count)
          return `'${sorted[i].name}' reicht über das Ende von '${output.name}' hinaus.`;
        if (i && sorted[i].start < sorted[i - 1].start + sorted[i - 1].count)
          return `'${sorted[i].name}' und '${sorted[i - 1].name}' überlappen sich auf '${output.name}'.`;
      }
    }
    if (wizSegmentCount() > MAX_SEGMENTS)
      return `Höchstens ${MAX_SEGMENTS} Abschnitte insgesamt.`;
    const pins = wizPinsInUse();
    if (new Set(pins).size !== pins.length)
      return 'Zwei Ausgänge liegen auf demselben GPIO.';
    if (pins.includes(WIZ.sbus_pin))
      return `GPIO ${WIZ.sbus_pin} ist der SBUS-Eingang.`;
  }

  if (step === 4) {
    // Every reserved bit has to switch something, or it is payload paid for
    // and wasted -- and the configuration check refuses it on save anyway.
    if (WIZ.relays_cfg.length !== WIZ.relays) {
      return WIZ.relays_cfg.length < WIZ.relays
        ? `${WIZ.relays - WIZ.relays_cfg.length} reserviertes Bit ohne Relais — `
          + 'entweder eins anlegen oder im Schritt Zonen weniger reservieren.'
        : 'Mehr Relais als reservierte Bits.';
    }
    if (WIZ.relays_cfg.some((relay) => !relay.name.trim()))
      return 'Jedes Relais braucht einen Namen — er steht auch auf der Leitung.';
    const names = WIZ.relays_cfg.map((relay) => relay.name.trim());
    if (new Set(names).size !== names.length)
      return 'Zwei Relais heißen gleich.';
    const pins = wizPinsInUse();
    if (new Set(pins).size !== pins.length)
      return 'Zwei Ausgänge liegen auf demselben GPIO.';
  }

  if (step === 5) {
    for (const nav of WIZ.navs) {
      const output = WIZ.outputs[nav.output];
      if (!output) return 'Ein Positionslicht zeigt auf einen Ausgang, den es nicht gibt.';
      if (nav.index >= output.count)
        return `Ein Positionslicht sitzt auf Pixel ${nav.index}, '${output.name}' hat ${output.count}.`;
    }
  }

  return '';
}

/* ------------------------------------------------------------------ build */

function wizBuild() {
  const name = WIZ.name.trim();
  const zones = WIZ.zones;

  const channels = [];
  for (let zone = 0; zone < zones; zone++) {
    channels.push({role: 'cue', quantize: 32, failsafe: 1000});
    channels.push({role: 'hue', failsafe: 1500});
    channels.push({role: 'brightness', failsafe: 1000});
    channels.push({role: 'param', failsafe: 1500});
  }

  const model = {
    name,
    tx_port: WIZ.tx_port,
    tx_offset: WIZ.tx_offset,
    channels,
    // One relay, two halves: the bit on the wire and the pin on the board.
    // Both lists come out of the same array, in the same order, so they cannot
    // drift apart.
    bus: {
      relays: WIZ.relays_cfg.map((relay) => ({
        name: relay.name.trim(), failsafe: false,
      })),
    },
    plane: {
      board: WIZ.board,
      airframe: WIZ.airframe,
      sbus_pin: WIZ.sbus_pin,
      max_brightness: WIZ.max_brightness,
      render_hz: WIZ.render_hz,
      outputs: WIZ.outputs.map((output) => ({
        name: output.name, pin: output.pin, count: output.count,
        segments: output.segments.map((segment) => ({...segment})),
      })),
      relays: WIZ.relays_cfg.map((relay) => ({
        name: relay.name.trim(), pin: relay.pin, active_low: relay.active_low,
        min_on_ms: relay.min_on_ms, min_off_ms: relay.min_off_ms,
      })),
      nav_lights: WIZ.navs.map((nav) => ({...nav, color: [...nav.color]})),
    },
  };

  // The jack has to be able to carry it, so the wizard's radio settings win.
  const port = CONFIG.tx_ports.find((entry) => entry.id === WIZ.tx_port);
  if (port) {
    port.format = WIZ.format;
    port.nchan = WIZ.nchan;
    port.frame_us = WIZ.format === 'ppm' ? WIZ.frame_us : 7000;
  }

  const at = CONFIG.models.findIndex((entry) => entry.name === WIZ.editing);
  if (at >= 0) CONFIG.models[at] = model;
  else CONFIG.models.push(model);

  // One rule, applied here rather than in three places: a jack that carries no
  // model is switched off. Deleting a model already did that for its own jack;
  // *moving* one did not, so the jack it left went on sending a frame out of a
  // socket nobody listens to any more, and the assistant went on offering it as
  // set up. Older workspaces have collected a few of those, and this is where
  // they get cleared -- `freeJack` never touches a jack a model still sits on.
  (CONFIG.tx_ports || []).forEach((entry) => freeJack(entry.id));
  return model;
}

/* ----------------------------------------------------------------- events */

/* Carries a choice made in the Zonen step through to the two steps that have
 * to live with it. Dropping zones must not leave a segment pointing into
 * nothing, and the number of bits picked there is the number of relays there
 * are -- so the Relais step gets exactly that many rows, no more and no less. */
function wizClampZones() {
  WIZ.outputs.forEach((output) => output.segments.forEach((segment) => {
    segment.zone = Math.min(segment.zone, WIZ.zones - 1);
  }));

  // Fewer bits than relays: the ones past the budget have no way to be
  // switched, so they go rather than sit there looking configured.
  if (WIZ.relays_cfg.length > WIZ.relays) WIZ.relays_cfg.length = WIZ.relays;
  // More bits than relays: a reserved bit that switches nothing is payload
  // paid for and wasted, so the rows appear right away.
  while (WIZ.relays_cfg.length < WIZ.relays) {
    WIZ.relays_cfg.push({
      name: `relais${WIZ.relays_cfg.length + 1}`, pin: wizNextPin('relay'),
      active_low: false, min_on_ms: 0, min_off_ms: 0,
    });
  }
}

function wizBind() {
  $('wizard').addEventListener('input', (event) => {
    if (!WIZ) return;
    const target = event.target;
    const value = target.type === 'checkbox' ? target.checked : target.value;

    const simple = {
      'wiz-name': 'name', 'wiz-port': 'tx_port',
      'wiz-format': 'format', 'wiz-nchan': 'nchan', 'wiz-frame': 'frame_us',
      'wiz-offset': 'tx_offset', 'wiz-sbus': 'sbus_pin',
      'wiz-maxbright': 'max_brightness', 'wiz-renderhz': 'render_hz',
    };
    if (simple[target.id]) {
      const key = simple[target.id];
      WIZ[key] = (key === 'name' || key === 'format') ? value : Number(value);
      if (key === 'nchan') {
        WIZ.frame_us = wizMinimumFrame(WIZ.nchan);
        wizLoadBus().then(wizRender);
      } else if (key === 'format') {
        // The step's own text depends on this one, and a select loses no
        // caret, so it is redrawn rather than merely revalidated.
        wizLoadBus().then(wizRender);
      } else if (key === 'frame_us') {
        wizLoadBus().then(wizRefreshFooter);
      } else if (key === 'tx_port') {
        // The jack belongs to the transmitter, not to the model. Sits another
        // model on it, then format, channel count and frame length are already
        // decided -- they are one signal out of one socket. Taking them over
        // beats writing this model's own over them, which is what happened
        // before: moving a 16 channel model onto an 8 channel jack quietly
        // changed the frame the neighbour rides in.
        const shared = wizNeighbours(WIZ.tx_port).length;
        const port = (CONFIG.tx_ports || []).find((p) => p.id === WIZ.tx_port);
        const frameWas = WIZ.frame_us;
        if (shared && port && port.format !== 'off') {
          WIZ.format = port.format;
          WIZ.nchan = port.nchan;
          WIZ.frame_us = port.frame_us;
        }
        // Landing on top of the model already there would only be found out on
        // save, so the wizard moves out of the way by itself. Deliberately not
        // done for a hand-typed offset: that is somebody saying where they want
        // it, and being overruled is worse than being told.
        const free = wizFreeOffset(WIZ.tx_port);
        if (free !== null && wizBlockClash()) WIZ.tx_offset = free;
        // The combination table is worked out for one frame length.
        if (WIZ.frame_us !== frameWas) wizLoadBus().then(wizRender);
        else wizRender();
        return;
      } else if (key !== 'name') {
        wizRender();
        return;
      }
      wizRefreshFooter();
      return;
    }

    const kind = target.dataset.wiz;
    const index = Number(target.dataset.i);
    const key = target.dataset.key;
    const asNumber = (v) => (target.type === 'checkbox' ? v : Number(v));

    if (kind === 'out' && WIZ.outputs[index]) {
      WIZ.outputs[index][key] = key === 'name' ? value : asNumber(value);
      // The GPIO list of every other output depends on this one, so a changed
      // pin is the one case worth a full redraw.
      if (key === 'pin') return wizRender();
      wizRefreshOutputs();
      wizRefreshFooter();
      return;
    }
    if (kind === 'seg') {
      const output = WIZ.outputs[Number(target.dataset.o)];
      const segment = output && output.segments[index];
      if (!segment) return;
      segment[key] = key === 'name' ? value : asNumber(value);
      wizRefreshOutputs();
      wizRefreshFooter();
      return;
    }
    if (kind === 'relay' && WIZ.relays_cfg[index]) {
      WIZ.relays_cfg[index][key] = key === 'name' ? value : asNumber(value);
      if (key === 'pin') return wizRender();     // frees or claims a GPIO
      wizRefreshFooter();
      return;
    }
    if (kind === 'nav' && WIZ.navs[index]) {
      WIZ.navs[index][key] = Number(value);
      if (key === 'output') wizRender();
      else wizRefreshFooter();
      return;
    }
    if (kind === 'nav-colour' && WIZ.navs[index]) {
      WIZ.navs[index].color = [1, 3, 5].map(
        (at) => parseInt(target.value.substr(at, 2), 16));
      wizRefreshFooter();
    }
  });

  $('wizard').addEventListener('click', (event) => {
    if (!WIZ) return;

    const tab = event.target.closest('[data-wiz="step"]');
    if (tab) { WIZ.step = Number(tab.dataset.step); return wizRender(); }

    const shape = event.target.closest('[data-wiz="airframe"]');
    if (shape) { WIZ.airframe = shape.dataset.key; return wizRender(); }

    const board = event.target.closest('[data-wiz="board"]');
    if (board) {
      WIZ.board = board.dataset.key;
      wizApplyBoard();
      return wizRender();
    }

    const combo = event.target.closest('[data-wiz="combo"]');
    if (combo) {
      WIZ.zones = Number(combo.dataset.zones);
      WIZ.relays = Number(combo.dataset.relays);
      wizClampZones();
      return wizRender();
    }

    const button = event.target.closest('button[data-wiz]');
    if (!button) return;
    const kind = button.dataset.wiz;
    const index = Number(button.dataset.i);

    if (kind === 'out-add') {
      WIZ.outputs.push({
        name: `streifen${WIZ.outputs.length + 1}`, pin: wizNextPin('led'), count: 30,
        // A fresh chain is one undivided section -- that is the common case,
        // and dividing it is one click away.
        segments: [{name: 'ganz', start: 0, count: 30,
                    zone: Math.min(WIZ.outputs.length, WIZ.zones - 1),
                    offset: 0, reverse: false}],
      });
      wizRender();
    } else if (kind === 'out-del') {
      WIZ.outputs.splice(index, 1);
      // Navigation lights name an output by position, so the ones above it move
      // down and the ones on it disappear with it.
      WIZ.navs = WIZ.navs.filter((nav) => nav.output !== index)
        .map((nav) => ({...nav, output: nav.output > index ? nav.output - 1 : nav.output}));
      wizRender();
    } else if (kind === 'seg-add') {
      const output = WIZ.outputs[index];
      const start = output.segments.reduce(
        (most, s) => Math.max(most, s.start + s.count), 0);
      output.segments.push({
        name: `teil${output.segments.length + 1}`, start,
        count: Math.max(1, output.count - start),
        zone: Math.min(output.segments.length, WIZ.zones - 1),
        offset: 0, reverse: false,
      });
      wizRender();
    } else if (kind === 'seg-split') {
      // Dividing a chain that is already fully claimed: halve a section and
      // give the second half to the next zone, which is what one wants nine
      // times out of ten.
      const output = WIZ.outputs[Number(button.dataset.o)];
      const segment = output.segments[index];
      const first = Math.floor(segment.count / 2);
      const rest = segment.count - first;
      segment.count = first;
      output.segments.splice(index + 1, 0, {
        name: `${segment.name}_2`, start: segment.start + first, count: rest,
        zone: Math.min(segment.zone + 1, WIZ.zones - 1),
        offset: segment.offset, reverse: segment.reverse,
      });
      wizRender();
    } else if (kind === 'seg-del') {
      WIZ.outputs[Number(button.dataset.o)].segments.splice(index, 1);
      wizRender();
    } else if (kind === 'relay-add') {
      WIZ.relays_cfg.push({
        name: `relais${WIZ.relays_cfg.length + 1}`, pin: wizNextPin('relay'),
        active_low: false, min_on_ms: 0, min_off_ms: 0,
      });
      wizRender();
    } else if (kind === 'relay-del') {
      WIZ.relays_cfg.splice(index, 1);
      wizRender();
    } else if (kind === 'nav-add') {
      const template = NAV_TEMPLATES[Number(button.dataset.t)];
      WIZ.navs.push({output: 0, index: 0,
                     color: template ? [...template.color] : [255, 255, 255]});
      wizRender();
    } else if (kind === 'nav-standard') {
      // Red to port, green to starboard, white aft -- whichever of them is
      // still missing, with only the place left to fill in.
      NAV_TEMPLATES.forEach((template) => {
        const there = WIZ.navs.some((nav) => navTemplate(nav.color) === template);
        if (!there && WIZ.navs.length < 16) {
          WIZ.navs.push({output: 0, index: 0, color: [...template.color]});
        }
      });
      wizRender();
    } else if (kind === 'nav-del') {
      WIZ.navs.splice(index, 1);
      wizRender();
    }
  });

  $('wiz-back').onclick = () => { WIZ.step = Math.max(0, WIZ.step - 1); wizRender(); };
  $('wiz-next').onclick = () => {
    WIZ.step = Math.min(WIZ_STEPS.length - 1, WIZ.step + 1);
    wizRender();
  };
  $('wiz-cancel').onclick = () => wizClose();
  $('wiz-create').onclick = async () => {
    const editing = WIZ.editing;
    const model = wizBuild();
    wizClose();
    renderModels();
    // Written straight out. Six steps of answers that are only in a browser tab
    // are six steps waiting to be lost, and the bridge takes the new
    // configuration on the spot -- so "angelegt" and "gespeichert" are the same
    // moment rather than two the user has to connect.
    if (await saveConfig({quiet: true})) {
      toast(editing ? `Modell '${model.name}' geändert und übernommen.`
                    : `Modell '${model.name}' angelegt und übernommen.`,
            'ok', 5000);
    }
  };
}

document.addEventListener('DOMContentLoaded', wizBind);
