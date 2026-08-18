/* Model wizard: builds a complete aircraft in four steps.
 *
 * Assembling one by hand means knowing which channels are free, how long a PPM
 * frame has to be for them, whether the zones still fit without bus mode, and
 * which relay source needs payload bits. That is a lot to hold in the head at
 * once, and every one of those answers already exists on the server -- so the
 * wizard asks rather than guesses. Nothing here re-implements a rule: frame
 * lengths and the zone/relay budget come from /api/bus.
 *
 * The result is appended to CONFIG and takes effect on Speichern, like every
 * other edit in the models view.
 */

const WIZ_STEPS = ['Fernsteuerung', 'Zonen', 'LED-Ausgänge', 'Relais'];

let WIZ = null;       // working state, null while the dialog is closed
let WIZ_BUS = null;   // last answer from /api/bus

const wizFreeGpio = () => {
  const used = new Set([0, 1]);                 // debug UART
  for (const model of (CONFIG ? CONFIG.models : [])) {
    const plane = model.plane;
    if (!plane) continue;
    used.add(plane.sbus_pin);
    (plane.strips || []).forEach((strip) => used.add(strip.pin));
    (plane.relays || []).forEach((relay) => used.add(relay.pin));
  }
  const free = [];
  for (let pin = 2; pin <= 22 && free.length < 24; pin++)
    if (!used.has(pin)) free.push(pin);
  return free;
};

/* A jack nobody drives yet, or the first one if all are taken. */
function wizFreePort() {
  const taken = new Set((CONFIG ? CONFIG.models : []).map((m) => m.tx_port));
  for (let id = 0; id < (CONFIG ? CONFIG.tx_ports.length : 0); id++)
    if (!taken.has(id)) return id;
  return 0;
}

function wizFreeMidiChannel() {
  const taken = new Set((CONFIG ? CONFIG.models : []).map((m) => m.midi_channel));
  for (let channel = 1; channel <= 16; channel++)
    if (!taken.has(channel)) return channel;
  return 1;
}

/* Control changes nobody in this show uses yet. */
function wizFreeCCs(count, midiChannel) {
  const taken = new Set();
  if (CONFIG && CONFIG.blackout_cc !== null) taken.add(CONFIG.blackout_cc);
  for (const model of (CONFIG ? CONFIG.models : [])) {
    if (model.midi_channel !== midiChannel) continue;
    for (const channel of model.channels) {
      taken.add(channel.cc);
      if (channel.cc_lsb != null) taken.add(channel.cc_lsb);
    }
    for (const relay of ((model.bus && model.bus.relays) || [])) taken.add(relay.cc);
  }
  const out = [];
  for (let cc = 20; cc <= 110 && out.length < count; cc++)
    if (!taken.has(cc)) out.push(cc);
  return out;
}

async function wizLoadBus() {
  const frame = WIZ.format === 'ppm' ? WIZ.frame_us : 7000;
  WIZ_BUS = await api(`/api/bus?frame_us=${frame}`);
  return WIZ_BUS;
}

/* How many channels are left for light, given where it starts. */
const wizFreeChannels = () => Math.max(0, WIZ.nchan - WIZ.tx_offset);

/* Bus mode is not a preference: below nine free channels it is the only way to
 * carry more than two zones, and the wizard says so rather than offering it. */
const wizNeedsBus = () => WIZ.zones * 4 > wizFreeChannels();

function wizMinimumFrame(nchan) {
  const table = WIZ_BUS && WIZ_BUS.ppm_frame_minimum;
  const value = table && table[String(nchan)];
  return value || 22500;
}

function wizOpen() {
  const midi = wizFreeMidiChannel();
  WIZ = {
    step: 0,
    name: '',
    midi_channel: midi,
    tx_port: wizFreePort(),
    format: 'ppm',
    nchan: 16,
    frame_us: 35500,
    tx_offset: 8,
    zones: 2,
    relays: 0,               // bus relays, chosen in step 2
    strips: [],
    relays_cfg: [],
    sbus_pin: 5,
  };
  wizLoadBus().then(() => {
    WIZ.frame_us = wizMinimumFrame(WIZ.nchan);
    wizRender();
  });
  $('wizard').showModal();
  wizRender();
}

function wizClose() {
  WIZ = null;
  $('wizard').close();
}

/* ------------------------------------------------------------------ steps */

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
          ${(CONFIG ? CONFIG.tx_ports : []).map((port) =>
            `<option value="${port.id}" ${WIZ.tx_port === port.id ? 'selected' : ''}
              >Buchse ${port.id + 1} · GP${portGpio(port.id)}</option>`).join('')}
        </select></div>
      <div><label class="lbl">MIDI-Kanal</label>
        <input type="number" id="wiz-midi" min="1" max="16"
          value="${WIZ.midi_channel}" style="width:100%"></div>
    </div>

    <h3 class="section">Signalform</h3>
    <div class="fgrid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">
      <div><label class="lbl">Format</label>
        <select id="wiz-format" style="width:100%">
          <option value="ppm" ${WIZ.format === 'ppm' ? 'selected' : ''}>PPM (Klinke)</option>
          <option value="sbus" ${WIZ.format === 'sbus' ? 'selected' : ''}>SBUS (seriell)</option>
        </select></div>
      <div><label class="lbl">Kanäle</label>
        <select id="wiz-nchan" style="width:100%">
          ${[4, 6, 8, 10, 12, 14, 16].map((n) =>
            `<option value="${n}" ${WIZ.nchan === n ? 'selected' : ''}>${n}</option>`).join('')}
        </select></div>
      <!-- Spelled out: the label is set in capitals, and a capital µ reads as M. -->
      <div><label class="lbl">Rahmenlänge in Mikrosekunden</label>
        <input type="number" id="wiz-frame" min="4000" max="60000" step="100"
          value="${WIZ.frame_us}" class="${tooShort ? 'err' : ''}" style="width:100%"></div>
      <div><label class="lbl">Licht beginnt bei Kanal</label>
        <input type="number" id="wiz-offset" min="0" max="15"
          value="${WIZ.tx_offset}" style="width:100%"></div>
    </div>

    ${tooShort ? `<div class="note warn" style="margin-top:12px">
      ${WIZ.nchan} Kanäle brauchen mindestens <b>${minimum} µs</b>. Kürzer nimmt die
      Bordfirmware den Rahmen nicht an.</div>` : ''}

    <div class="note" style="margin-top:14px">
      <b>${free}</b> Kanäle stehen dem Licht zur Verfügung (${WIZ.tx_offset + 1}–${WIZ.nchan}),
      ein Rahmen dauert <b>${cueRate.toFixed(1)} ms</b>.
      ${WIZ.tx_offset > 0 ? `Die Kanäle 1–${WIZ.tx_offset} bleiben den Knüppeln.` :
        'Achtung: das Licht beginnt bei Kanal 1, es bleibt nichts für Knüppel und Schalter.'}
    </div>`;
}

function wizStepZones() {
  const free = wizFreeChannels();
  const needsBus = wizNeedsBus();
  const table = (WIZ_BUS && WIZ_BUS.ports && WIZ_BUS.ports.asked)
    ? WIZ_BUS.ports.asked.combinations : [];
  const limit = WIZ_BUS ? WIZ_BUS.limit_ms : 150;

  const matrix = busMatrix(table, WIZ.zones, WIZ.relays,
    (zones, relays) => `data-wiz="combo" data-zones="${zones}" data-relays="${relays}"`);

  return `
    <p class="muted" style="margin:0 0 14px">Eine Zone ist ein Stück Beleuchtung, das
      gemeinsam geschaltet wird — etwa eine Tragfläche. Vier Kanäle je Zone:
      Effekt, Farbe, Helligkeit, Tempo.</p>

    <div class="fgrid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">
      <div><label class="lbl">Zonen</label>
        <input type="number" id="wiz-zones" min="1" max="8" value="${WIZ.zones}"
          style="width:100%"></div>
    </div>

    ${needsBus ? `
      <div class="note warn" style="margin-top:14px">
        ${WIZ.zones} Zonen brauchen ${WIZ.zones * 4} Kanäle, frei sind <b>${free}</b>.
        Das geht nur im <b>Bus-Modus</b>: die acht Kanäle tragen dann einen codierten
        Rahmen, der die Zonen reihum bedient. Der Preis ist Wartezeit — unten steht,
        wie viel.
      </div>` : `
      <div class="note ok" style="margin-top:14px">
        ${WIZ.zones} Zonen passen in die ${free} freien Kanäle, ganz ohne Bus-Modus.
        Jede Zone wird in jedem Rahmen aktualisiert.
      </div>`}

    <h3 class="section">Kombination wählen</h3>
    <p class="muted" style="margin:0 0 10px;font-size:12.5px">
      Jede Kachel ist eine mögliche Aufteilung samt der Wartezeit, bis dieselbe Zone
      wieder an der Reihe ist. Relais <b>am Bus</b> werden direkt geschaltet und kosten
      Nutzbits — daher der Abtausch. Relais, die einem Effekt folgen, kosten nichts und
      werden im nächsten Schritt eingerichtet. Blass hinterlegt heißt: langsamer als die
      eingestellte Grenze von ${limit} ms.
      ${!needsBus && !WIZ.relays ? `<br>Solange keine Bus-Relais gewählt sind, kommt
        dieses Modell ohne Bus-Modus aus und jede Zone wird in jedem Rahmen
        aktualisiert — die Wartezeit gilt dann nicht.` : ''}
    </p>
    ${matrix}`;
}

function wizStepStrips() {
  const free = wizFreeGpio();
  const rows = WIZ.strips.map((strip, index) => `
    <tr>
      <td><input type="text" value="${esc(strip.name)}" style="width:130px"
        data-wiz="strip" data-i="${index}" data-key="name"></td>
      <td><select style="width:80px" data-wiz="strip" data-i="${index}" data-key="pin">
        ${free.concat([strip.pin]).filter((v, i, a) => a.indexOf(v) === i)
          .sort((a, b) => a - b).map((pin) =>
            `<option value="${pin}" ${strip.pin === pin ? 'selected' : ''}>GP${pin}</option>`).join('')}
      </select></td>
      <td><input type="number" min="1" max="256" value="${strip.count}" style="width:76px"
        data-wiz="strip" data-i="${index}" data-key="count"></td>
      <td><select style="width:90px" data-wiz="strip" data-i="${index}" data-key="zone">
        ${Array.from({length: WIZ.zones}, (_, zone) =>
          `<option value="${zone}" ${strip.zone === zone ? 'selected' : ''}>Zone ${zone + 1}</option>`).join('')}
      </select></td>
      <td><input type="number" min="0" max="255" value="${strip.offset}" style="width:76px"
        data-wiz="strip" data-i="${index}" data-key="offset"></td>
      <td><input type="checkbox" ${strip.reverse ? 'checked' : ''}
        data-wiz="strip" data-i="${index}" data-key="reverse"></td>
      <td><button class="quiet" data-wiz="strip-del" data-i="${index}">−</button></td>
    </tr>`).join('');

  const perZone = Array.from({length: WIZ.zones}, (_, zone) => {
    const mine = WIZ.strips.filter((s) => s.zone === zone);
    const pixels = mine.reduce((most, s) => Math.max(most, s.offset + s.count), 0);
    return `<li>Zone ${zone + 1}: ${mine.length
      ? `${mine.map((s) => esc(s.name)).join(', ')} — ${pixels} Pixel lang`
      : '<span class="warn-text">noch nichts angeschlossen</span>'}</li>`;
  }).join('');

  return `
    <p class="muted" style="margin:0 0 14px">Welcher LED-Streifen an welchem GPIO hängt
      und zu welcher Zone er gehört. Der <b>Offset</b> ist die Position im Lauflicht
      der Zone: zwei Streifen mit demselben Offset spiegeln sich, hintereinander
      gesetzte ergeben eine lange Kette.</p>

    <div class="tablewrap"><table class="form">
      <thead><tr><th>Name</th><th>GPIO</th><th>Pixel</th><th>Zone</th>
        <th>Offset</th><th>rückwärts</th><th></th></tr></thead>
      <tbody>${rows || '<tr><td colspan="7" class="dim">noch keine Streifen</td></tr>'}</tbody>
    </table></div>
    <button data-wiz="strip-add" style="margin-top:10px"
      ${WIZ.strips.length >= 8 ? 'disabled' : ''}>＋ LED-Streifen</button>
    <span class="dim" style="font-size:12px;margin-left:10px">${WIZ.strips.length}/8 —
      mehr geht nicht, es gibt acht PIO-Zustandsmaschinen.</span>

    <h3 class="section">Was jede Zone dann treibt</h3>
    <ul class="wiz-list">${perZone}</ul>`;
}

function wizStepRelays() {
  const free = wizFreeGpio();
  const sources = WIZ.relays
    ? RELAY_SOURCES.concat([['bus', 'direkt über den Bus']])
    : RELAY_SOURCES;

  const rows = WIZ.relays_cfg.map((relay, index) => `
    <tr>
      <td><input type="text" value="${esc(relay.name)}" style="width:120px"
        data-wiz="relay" data-i="${index}" data-key="name"></td>
      <td><select style="width:80px" data-wiz="relay" data-i="${index}" data-key="pin">
        ${free.concat([relay.pin]).filter((v, i, a) => a.indexOf(v) === i)
          .sort((a, b) => a - b).map((pin) =>
            `<option value="${pin}" ${relay.pin === pin ? 'selected' : ''}>GP${pin}</option>`).join('')}
      </select></td>
      <td><select style="width:90px" data-wiz="relay" data-i="${index}" data-key="zone">
        ${Array.from({length: WIZ.zones}, (_, zone) =>
          `<option value="${zone}" ${relay.zone === zone ? 'selected' : ''}>Zone ${zone + 1}</option>`).join('')}
      </select></td>
      <td><select style="width:150px" data-wiz="relay" data-i="${index}" data-key="source">
        ${sources.map(([value, label]) =>
          `<option value="${value}" ${relay.source === value ? 'selected' : ''}>${label}</option>`).join('')}
      </select></td>
      <td><input type="number" min="0" max="255" value="${relay.arg}" style="width:70px"
        data-wiz="relay" data-i="${index}" data-key="arg"
        title="${relay.source === 'bus' ? 'Steckplatz im Bus-Rahmen'
          : relay.source === 'cue' ? 'ab dieser Cue-Nummer'
          : relay.source === 'pixel' ? 'Pixelindex' : 'RC-Kanal'}"></td>
      <td><input type="number" min="0" max="255" value="${relay.threshold}" style="width:70px"
        data-wiz="relay" data-i="${index}" data-key="threshold"
        ${relay.source === 'bus' || relay.source === 'cue' ? 'disabled' : ''}></td>
      <td><input type="checkbox" ${relay.active_low ? 'checked' : ''}
        data-wiz="relay" data-i="${index}" data-key="active_low"></td>
      <td><input type="number" min="0" max="5000" step="50" value="${relay.min_on_ms}" style="width:76px"
        data-wiz="relay" data-i="${index}" data-key="min_on_ms"></td>
      <td><button class="quiet" data-wiz="relay-del" data-i="${index}">−</button></td>
    </tr>`).join('');

  const busUsed = WIZ.relays_cfg.filter((r) => r.source === 'bus').length;

  return `
    <p class="muted" style="margin:0 0 14px">Ein Relais schaltet etwas, das keine LED ist —
      Scheinwerfer, Rauch, Landelicht. <b>Folgt es einem Effekt</b> (Pixel, Dimmer, Cue),
      kostet es nichts über die Luft. <b>Direkt über den Bus</b> geschaltet bekommt es ein
      eigenes Bit und ist unabhängig von der Zone.</p>

    ${WIZ.relays ? `<div class="note" style="margin-bottom:12px">
      Im vorigen Schritt sind <b>${WIZ.relays}</b> Bus-Steckplätze reserviert,
      ${busUsed} davon vergeben. Der Steckplatz steht in der Spalte <i>Wert</i>.
    </div>` : ''}

    <div class="tablewrap"><table class="form">
      <thead><tr><th>Name</th><th>GPIO</th><th>Zone</th><th>Quelle</th><th>Wert</th>
        <th>Schwelle</th><th>invertiert</th><th>min. an (ms)</th><th></th></tr></thead>
      <tbody>${rows || '<tr><td colspan="9" class="dim">noch keine Relais</td></tr>'}</tbody>
    </table></div>
    <button data-wiz="relay-add" style="margin-top:10px"
      ${WIZ.relays_cfg.length >= 8 ? 'disabled' : ''}>＋ Relais</button>
    <span class="dim" style="font-size:12px;margin-left:10px">${WIZ.relays_cfg.length}/8</span>

    <div class="note" style="margin-top:14px">
      <b>invertiert</b> für fertige Relaismodule, die bei LOW schalten.
      <b>min. an</b> schützt ein mechanisches Relais vor dem Klappern in einem Strobe —
      0 für MOSFETs, etwa 200 ms für ein echtes Relais.
    </div>`;
}

/* ----------------------------------------------------------------- render */

function wizRender() {
  if (!WIZ) return;
  const body = $('wiz-body');
  const steps = [wizStepRadio, wizStepZones, wizStepStrips, wizStepRelays];
  body.innerHTML = steps[WIZ.step]();

  $('wiz-steps').innerHTML = WIZ_STEPS.map((label, index) =>
    `<span class="wiz-step ${index === WIZ.step ? 'on' : ''} ${index < WIZ.step ? 'done' : ''}">
      ${index + 1}. ${label}</span>`).join('');

  $('wiz-back').disabled = WIZ.step === 0;
  $('wiz-next').classList.toggle('hidden', WIZ.step === WIZ_STEPS.length - 1);
  $('wiz-create').classList.toggle('hidden', WIZ.step !== WIZ_STEPS.length - 1);

  const problem = wizProblem();
  $('wiz-next').disabled = !!problem;
  $('wiz-create').disabled = !!problem;
  $('wiz-note').textContent = problem || '';
  $('wiz-note').classList.toggle('hidden', !problem);
}

/* What stops this step from being finished, in one sentence. */
function wizProblem() {
  if (WIZ.step === 0) {
    if (!WIZ.name.trim()) return 'Das Modell braucht einen Namen.';
    if (!/^[a-z0-9_]+$/.test(WIZ.name.trim()))
      return 'Nur Kleinbuchstaben, Ziffern und Unterstrich — der Name wird ein Dateiname.';
    if ((CONFIG ? CONFIG.models : []).some((m) => m.name === WIZ.name.trim()))
      return `Ein Modell '${WIZ.name.trim()}' gibt es schon.`;
    if (WIZ.format === 'ppm' && WIZ.frame_us < wizMinimumFrame(WIZ.nchan))
      return `Der Rahmen ist zu kurz für ${WIZ.nchan} Kanäle.`;
    if (wizFreeChannels() < 4)
      return 'Es bleiben weniger als vier Kanäle für das Licht.';
  }
  if (WIZ.step === 1) {
    if (wizNeedsBus() && wizFreeChannels() < 8)
      return 'Der Bus-Modus braucht acht freie Kanäle.';
    if (WIZ.zones < 1 || WIZ.zones > 8) return 'Zwischen einer und acht Zonen.';
  }
  if (WIZ.step === 2) {
    const empty = Array.from({length: WIZ.zones}, (_, zone) => zone)
      .filter((zone) => !WIZ.strips.some((s) => s.zone === zone));
    if (empty.length)
      return `Zone ${empty.map((z) => z + 1).join(', ')} hat noch keinen LED-Streifen.`;
  }
  if (WIZ.step === 3) {
    const slots = WIZ.relays_cfg.filter((r) => r.source === 'bus').map((r) => r.arg);
    if (slots.some((slot) => slot >= WIZ.relays))
      return `Ein Relais zeigt auf einen Bus-Steckplatz, den es nicht gibt (0–${WIZ.relays - 1}).`;
    if (new Set(slots).size !== slots.length)
      return 'Zwei Relais teilen sich denselben Bus-Steckplatz.';
    const pins = WIZ.strips.map((s) => s.pin).concat(WIZ.relays_cfg.map((r) => r.pin));
    if (new Set(pins).size !== pins.length) return 'Zwei Ausgänge liegen auf demselben GPIO.';
  }
  return '';
}

/* ------------------------------------------------------------------ build */

function wizBuild() {
  const name = WIZ.name.trim();
  const zones = WIZ.zones;
  const bus = wizNeedsBus() || WIZ.relays > 0;
  const ccs = wizFreeCCs(zones * 5 + WIZ.relays, WIZ.midi_channel);
  let next = 0;

  const channels = [];
  for (let zone = 0; zone < zones; zone++) {
    channels.push({role: 'cue', cc: ccs[next++], quantize: 32, failsafe: 1000});
    channels.push({role: 'hue', cc: ccs[next++], failsafe: 1500});
    channels.push({role: 'brightness', cc: ccs[next++],
                   cc_lsb: ccs[next++], failsafe: 1000});
    channels.push({role: 'param', cc: ccs[next++], failsafe: 1500});
  }

  const model = {
    name,
    midi_channel: WIZ.midi_channel,
    tx_port: WIZ.tx_port,
    tx_offset: WIZ.tx_offset,
    channels,
    plane: {
      board: 'pico',
      sbus_pin: WIZ.sbus_pin,
      max_brightness: 200,
      render_hz: 200,
      strips: WIZ.strips.map((strip) => ({...strip})),
      relays: WIZ.relays_cfg.map((relay) => ({...relay})),
      nav_lights: [],
    },
  };

  if (bus) {
    model.bus = {
      enabled: true,
      relays: Array.from({length: WIZ.relays}, (_, index) => ({
        name: (WIZ.relays_cfg.find((r) => r.source === 'bus' && r.arg === index) || {})
          .name || `bus${index}`,
        cc: ccs[next++],
        failsafe: false,
      })),
    };
  }

  // The jack has to be able to carry it, so the wizard's radio settings win.
  const port = CONFIG.tx_ports.find((entry) => entry.id === WIZ.tx_port);
  if (port) {
    port.format = WIZ.format;
    port.nchan = WIZ.nchan;
    port.frame_us = WIZ.format === 'ppm' ? WIZ.frame_us : 7000;
  }

  CONFIG.models.push(model);
  return model;
}

/* ----------------------------------------------------------------- events */

function wizBind() {
  $('wizard').addEventListener('input', (event) => {
    if (!WIZ) return;
    const target = event.target;
    const value = target.type === 'checkbox' ? target.checked : target.value;

    const simple = {
      'wiz-name': 'name', 'wiz-midi': 'midi_channel', 'wiz-port': 'tx_port',
      'wiz-format': 'format', 'wiz-nchan': 'nchan', 'wiz-frame': 'frame_us',
      'wiz-offset': 'tx_offset', 'wiz-zones': 'zones',
    };
    if (simple[target.id]) {
      const key = simple[target.id];
      WIZ[key] = key === 'name' || key === 'format' ? value : Number(value);
      if (key === 'nchan') {
        WIZ.frame_us = wizMinimumFrame(WIZ.nchan);
        wizLoadBus().then(wizRender);
      }
      if (key === 'frame_us' || key === 'format') wizLoadBus().then(wizRender);
      if (key === 'zones') {
        // Strips and relays point at zones; dropping zones must not leave them
        // pointing into nothing.
        WIZ.strips.forEach((s) => { s.zone = Math.min(s.zone, WIZ.zones - 1); });
        WIZ.relays_cfg.forEach((r) => { r.zone = Math.min(r.zone, WIZ.zones - 1); });
      }
      if (key !== 'nchan' && key !== 'frame_us' && key !== 'format') wizRender();
      else if (target.id === 'wiz-name') { /* keep focus, no re-render */ }
      return;
    }

    const kind = target.dataset.wiz;
    const index = Number(target.dataset.i);
    const key = target.dataset.key;
    if (kind === 'strip' && WIZ.strips[index]) {
      WIZ.strips[index][key] = ['name'].includes(key) ? value
        : (target.type === 'checkbox' ? value : Number(value));
    } else if (kind === 'relay' && WIZ.relays_cfg[index]) {
      WIZ.relays_cfg[index][key] = ['name', 'source'].includes(key) ? value
        : (target.type === 'checkbox' ? value : Number(value));
      if (key === 'source') wizRender();
    }
    wizRefreshFooter();
  });

  $('wizard').addEventListener('click', (event) => {
    if (!WIZ) return;
    const combo = event.target.closest('[data-wiz="combo"]');
    if (combo) {
      WIZ.zones = Number(combo.dataset.zones);
      WIZ.relays = Number(combo.dataset.relays);
      WIZ.strips.forEach((s) => { s.zone = Math.min(s.zone, WIZ.zones - 1); });
      WIZ.relays_cfg.forEach((r) => { r.zone = Math.min(r.zone, WIZ.zones - 1); });
      return wizRender();
    }

    const kind = event.target.dataset ? event.target.dataset.wiz : null;
    const index = Number(event.target.dataset ? event.target.dataset.i : 0);
    const free = wizFreeGpio();
    const takenPins = new Set(WIZ.strips.map((s) => s.pin)
      .concat(WIZ.relays_cfg.map((r) => r.pin)));
    const nextPin = free.find((pin) => !takenPins.has(pin)) || 2;

    if (kind === 'strip-add') {
      WIZ.strips.push({name: `streifen${WIZ.strips.length + 1}`, pin: nextPin,
                       count: 30, zone: Math.min(WIZ.strips.length, WIZ.zones - 1),
                       offset: 0, reverse: false});
      wizRender();
    } else if (kind === 'strip-del') {
      WIZ.strips.splice(index, 1);
      wizRender();
    } else if (kind === 'relay-add') {
      const slot = WIZ.relays_cfg.filter((r) => r.source === 'bus').length;
      WIZ.relays_cfg.push({
        name: `relais${WIZ.relays_cfg.length + 1}`, pin: nextPin, zone: 0,
        source: WIZ.relays && slot < WIZ.relays ? 'bus' : 'cue',
        arg: WIZ.relays && slot < WIZ.relays ? slot : 1,
        threshold: 64, active_low: false, min_on_ms: 0, min_off_ms: 0,
      });
      wizRender();
    } else if (kind === 'relay-del') {
      WIZ.relays_cfg.splice(index, 1);
      wizRender();
    }
  });

  $('wiz-back').onclick = () => { WIZ.step = Math.max(0, WIZ.step - 1); wizRender(); };
  $('wiz-next').onclick = () => {
    WIZ.step = Math.min(WIZ_STEPS.length - 1, WIZ.step + 1);
    wizRender();
  };
  $('wiz-cancel').onclick = () => wizClose();
  $('wiz-create').onclick = () => {
    const model = wizBuild();
    wizClose();
    renderModels();
    markDirty(true);
    toast(`Modell '${model.name}' angelegt — noch nicht gespeichert.`, 'ok', 6000);
  };
}

/* Only the footer, so typing in a text field does not lose the caret. */
function wizRefreshFooter() {
  const problem = wizProblem();
  $('wiz-next').disabled = !!problem;
  $('wiz-create').disabled = !!problem;
  $('wiz-note').textContent = problem || '';
  $('wiz-note').classList.toggle('hidden', !problem);
}

document.addEventListener('DOMContentLoaded', wizBind);
