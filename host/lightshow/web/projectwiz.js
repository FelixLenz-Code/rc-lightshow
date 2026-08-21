/* Creating a project: what it is called, and which aircraft fly in it.
 *
 * Two questions, so it could have been one dialogue with two fields. It is a
 * wizard anyway, and wears the model wizard's chrome -- the same step chips,
 * the same back/next, the same one-sentence complaint at the bottom. Creating a
 * project and creating a model are the same kind of act, and the second one
 * should not feel like a different program.
 *
 * What comes out is a name and a list of model names; the bridge lays the
 * tracks. Which models exist is not asked here and cannot be edited here --
 * that is the Modelle tab, and having one place for it is the point.
 */

const PW_STEPS = ['Name', 'Modelle'];

let PW = null;            // null while the dialogue is closed
let PW_MODELS = [];       // what the bridge says there is, from /api/projects

/* `project` is null for a new one, or {name, models} for one to rework; `dir`
 * says which folder that is, open or not. */
function pwOpen(models, project = null, dir = null) {
  PW_MODELS = models || [];
  PW = {
    step: 0,
    editing: project ? (dir || PROJECT_OPEN || true) : null,
    // Renaming the one on screen has to reach the editor; renaming a closed one
    // only has to reach the disk, and must not disturb what is open.
    isOpen: !!project && (dir === null || dir === PROJECT_OPEN),
    name: project ? project.name : pwFreeName(),
    was: project ? new Set(project.models || []) : null,
    // Everything ticked to start with: a field usually flies what it has, and
    // unticking two is less work than ticking three. One per transmitter,
    // though -- see `pwSameJack`.
    chosen: new Set(project ? (project.models || []) : pwDefaultChoice()),
  };
  document.querySelector('#projwiz h2').textContent =
    project ? `Projekt „${project.name}“` : 'Neues Projekt';
  $('pw-create').textContent = project ? 'Übernehmen' : 'Projekt anlegen';
  pwRender();
  $('projwiz').showModal();
}

/* Everything, minus whatever would collide on a transmitter. */
function pwDefaultChoice() {
  const seen = new Set();
  return PW_MODELS.filter((model) => {
    if (seen.has(model.tx_port)) return false;
    seen.add(model.tx_port);
    return true;
  }).map((model) => model.name);
}

/* Which already-chosen model shares this one's transmitter jack.
 *
 * Two models on one jack take different channel blocks out of the same frame,
 * so they can be built and flown -- but they hang on one transmitter, and a
 * show drives one of them or the other. Letting both into a project would put
 * two timelines on one stick. */
function pwSameJack(model) {
  const clash = PW_MODELS.find((other) => other.name !== model.name
    && other.tx_port === model.tx_port && PW.chosen.has(other.name));
  return clash ? clash.name : null;
}

const pwClose = () => { PW = null; $('projwiz').close(); };

/* A name that is not taken yet, so the field starts usable rather than red. */
function pwFreeName() {
  const taken = new Set((PROJECTS || []).map((entry) => entry.name.toLowerCase()));
  if (!taken.has('nachtflug')) return 'Nachtflug';
  for (let n = 2; ; n++) {
    if (!taken.has(`nachtflug ${n}`)) return `Nachtflug ${n}`;
  }
}

/* ------------------------------------------------------------------ step 0 */

function pwStepName() {
  return `
    ${PW.editing && !PW.isOpen ? `<div class="note" style="margin:0 0 14px">
      Dieses Projekt ist gerade <b>nicht geöffnet</b>. Geändert wird es
      trotzdem — geschrieben wird direkt in seinen Ordner, und was im Reiter
      <b>Show</b> steht, bleibt, wo es ist.</div>` : ''}
    <p class="muted" style="margin:0 0 14px">Wie die Show heißt.${PW.editing
      ? ' Der Ordner bleibt, wo er ist — ihn mitzuverschieben würde jeden Pfad'
        + ' brechen, der hineinzeigt, der Ordentlichkeit zuliebe.'
      : ' Der Name steht im Projektreiter und wird zum Ordnernamen unter'
        + ' <code>projects/</code> — Umlaute und Leerzeichen sind erlaubt, der'
        + ' Ordner bekommt eine abgeschliffene Fassung davon.'}</p>

    <div class="fgrid" style="grid-template-columns:minmax(220px,420px)">
      <div><label class="lbl" for="pw-name">Name des Projekts</label>
        <input type="text" id="pw-name" value="${esc(PW.name)}"
          placeholder="z. B. Nachtflug" style="width:100%"></div>
    </div>

    <div class="note" style="margin-top:14px">Ein Projekt ist ein Ordner: die
      <code>project.json</code> mit Spuren und Blöcken, daneben die importierten
      Audiodateien. Kopieren heißt kopieren, sichern heißt sichern.</div>`;
}

/* ------------------------------------------------------------------ step 1 */

function pwStepModels() {
  if (!PW_MODELS.length) {
    return `<div class="note warn">Es ist noch kein Modell eingerichtet. Im
      Reiter <b>Modelle</b> eines anlegen — ohne Flugzeug hat eine Show nichts,
      worauf sie spielen könnte.</div>`;
  }

  const card = (model) => {
    const on = PW.chosen.has(model.name);
    const blocked = on ? null : pwSameJack(model);
    const shape = (typeof WIZ_AIRFRAMES !== 'undefined'
      && WIZ_AIRFRAMES[model.airframe]) || null;
    const tracks = model.zones + model.relays;
    // Losing tracks is worth saying before it happens, not after.
    const losing = PW.editing && PW.was.has(model.name) && !on;
    return `
      <button class="wiz-board wiz-kind ${on ? 'on' : ''} ${blocked ? 'blocked' : ''}"
        data-pw="model" data-name="${esc(model.name)}" aria-pressed="${on}"
        ${blocked ? `title="Teilt sich Sender-Buchse ${model.tx_port + 1} mit '${esc(blocked)}'"` : ''}>
        ${shape ? shape.icon : ''}
        <div class="wiz-board-text">
          <b>${esc(model.name)}</b>
          <span>Buchse ${model.tx_port + 1} · ${model.zones} Zone${
            model.zones === 1 ? '' : 'n'}${
            model.relays ? ` · ${model.relays} Bus-Relais` : ''}${
            model.has_plane ? '' : ' · keine Bordkonfiguration'}</span>
          <span>${blocked
            ? `teilt sich die Buchse mit <b>${esc(blocked)}</b> — nur eines von beiden`
            : losing
              ? `<span class="warn-text">${tracks} Spur${tracks === 1 ? '' : 'en'} samt Blöcken fallen weg</span>`
              : `${tracks} Spur${tracks === 1 ? '' : 'en'}${
                  PW.editing && PW.was.has(model.name) ? ' bleiben' : ' werden angelegt'}`}</span>
        </div>
      </button>`;
  };

  const chosen = PW_MODELS.filter((model) => PW.chosen.has(model.name));
  const tracks = chosen.reduce((sum, m) => sum + m.zones + m.relays, 0);
  const dropped = PW.editing
    ? [...PW.was].filter((name) => !PW.chosen.has(name)) : [];

  return `
    <p class="muted" style="margin:0 0 14px">Welche Flugzeuge fliegen in dieser
      Show? Für jedes gewählte Modell entsteht je Zone eine Lichtspur und je
      Bus-Relais eine Relaisspur, benannt wie das Modell. Was hier nicht dabei
      ist, taucht in der Timeline nicht auf — ein Platz mit vier eingerichteten
      Modellen fliegt selten alle vier auf einmal.</p>

    <div class="wiz-boards">${PW_MODELS.map(card).join('')}</div>

    <div class="note ${chosen.length ? 'ok' : 'warn'}" style="margin-top:14px">
      ${chosen.length
        ? `<b>${chosen.map((m) => esc(m.name)).join(', ')}</b> — dazu zwei
           Audiospuren (Musik, Effekte). Macht ${tracks + 2} Spuren.`
        : 'Noch kein Modell gewählt.'}
    </div>

    ${dropped.length ? `<div class="note err" style="margin-top:10px">
      <b>${dropped.map(esc).join(', ')}</b> ${dropped.length === 1 ? 'fällt' : 'fallen'}
      aus dem Projekt. Die zugehörigen Spuren werden entfernt — mit allem, was
      darauf liegt. Das lässt sich nicht zurücknehmen.</div>` : ''}`;
}

const PW_RENDERERS = [pwStepName, pwStepModels];

/* ------------------------------------------------------------------ render */

function pwRender() {
  if (!PW) return;
  $('pw-body').innerHTML = PW_RENDERERS[PW.step]();

  $('pw-steps').innerHTML = PW_STEPS.map((label, index) => {
    const problem = pwProblem(index);
    return `<span class="wiz-step ${index === PW.step ? 'on' : ''}
      ${problem ? 'bad' : 'done'}" data-pw="step" data-step="${index}"
      >${index + 1}. ${esc(label)}${problem ? ' ⚠' : ''}</span>`;
  }).join('');

  const last = PW.step === PW_STEPS.length - 1;
  $('pw-back').disabled = PW.step === 0;
  $('pw-next').classList.toggle('hidden', last);
  // Same as the model wizard: a project being reworked can be taken from either
  // step, a new one has to be finished first.
  $('pw-create').classList.toggle('hidden', !last && !PW.editing);
  $('pw-create').classList.toggle('primary', last);

  const anywhere = pwFirstProblem();
  $('pw-create').disabled = !!anywhere;

  const here = pwProblem(PW.step);
  const note = $('pw-note');
  note.classList.toggle('hidden', !here && !anywhere);
  note.textContent = here || (anywhere
    ? `${anywhere[0] + 1}. ${PW_STEPS[anywhere[0]]}: ${anywhere[1]}` : '');

  const field = $('pw-name');
  if (field) {
    field.oninput = () => { PW.name = field.value; pwRenderNote(); };
    if (PW.step === 0) field.focus();
  }
}

/* The steps and the complaint, without redrawing the field somebody is typing
 * into -- which would put the caret back at the start on every keystroke. */
function pwRenderNote() {
  const anywhere = pwFirstProblem();
  const here = pwProblem(PW.step);
  const note = $('pw-note');
  note.classList.toggle('hidden', !here && !anywhere);
  note.textContent = here || (anywhere
    ? `${anywhere[0] + 1}. ${PW_STEPS[anywhere[0]]}: ${anywhere[1]}` : '');
  $('pw-create').disabled = !!anywhere;
  $('pw-steps').querySelectorAll('.wiz-step').forEach((chip, index) => {
    const problem = pwProblem(index);
    chip.classList.toggle('bad', !!problem);
    chip.classList.toggle('done', !problem);
    chip.textContent = `${index + 1}. ${PW_STEPS[index]}${problem ? ' ⚠' : ''}`;
  });
}

function pwFirstProblem() {
  for (let step = 0; step < PW_STEPS.length; step++) {
    const problem = pwProblem(step);
    if (problem) return [step, problem];
  }
  return null;
}

function pwProblem(step) {
  if (step === 0) {
    const name = PW.name.trim();
    if (!name) return 'Das Projekt braucht einen Namen.';
    // The folder is what the bridge would refuse, so it is what gets checked.
    const folder = pwFolderName(name);
    if (!folder) return 'Aus diesem Namen wird kein Ordnername — mindestens ein '
      + 'Buchstabe oder eine Ziffer.';
    // Renaming leaves the folder where it is, so an existing folder only
    // stands in the way when a new project is being made.
    if (!PW.editing && (PROJECTS || []).some((entry) => entry.dir === folder))
      return `Den Ordner '${folder}' gibt es schon.`;
    if ((PROJECTS || []).some((entry) => entry.dir !== PW.editing
        && entry.name.trim().toLowerCase() === name.toLowerCase()))
      return `Ein Projekt „${name}“ gibt es schon.`;
  }
  if (step === 1) {
    if (!PW_MODELS.length) return 'Erst ein Modell im Reiter Modelle anlegen.';
    if (!PW.chosen.size) return 'Mindestens ein Modell wählen.';
  }
  return null;
}

/* `safe_name` from project.py, character for character, so the dialogue can say
 * "that one exists" before the bridge has to. Getting this wrong is worse than
 * not having it: it would clear a name the bridge then refuses. */
function pwFolderName(name) {
  return name.trim().replace(/[^A-Za-z0-9_.\-]+/g, '_').replace(/^[._]+|[._]+$/g, '');
}

/* ------------------------------------------------------------------ wiring */

function pwBind() {
  $('projwiz').addEventListener('click', (event) => {
    if (!PW) return;

    const chip = event.target.closest('[data-pw="step"]');
    if (chip) { PW.step = Number(chip.dataset.step); return pwRender(); }

    const card = event.target.closest('[data-pw="model"]');
    if (card) {
      const name = card.dataset.name;
      if (PW.chosen.has(name)) { PW.chosen.delete(name); return pwRender(); }
      const model = PW_MODELS.find((m) => m.name === name);
      const clash = pwSameJack(model);
      if (clash) {
        // Swapping is what was meant: nobody clicks the second model on a jack
        // hoping for both. Saying so beats a button that does nothing.
        PW.chosen.delete(clash);
        toast(`'${clash}' abgewählt — beide hängen an Sender-Buchse `
              + `${model.tx_port + 1}.`, 'ok', 4000);
      }
      PW.chosen.add(name);
      return pwRender();
    }
  });

  $('pw-back').onclick = () => { PW.step = Math.max(0, PW.step - 1); pwRender(); };
  $('pw-next').onclick = () => {
    PW.step = Math.min(PW_STEPS.length - 1, PW.step + 1);
    pwRender();
  };
  $('pw-cancel').onclick = () => pwClose();

  $('pw-create').onclick = async () => {
    const name = PW.name.trim();
    // In the configuration's order, not in the order they were clicked.
    const models = PW_MODELS.map((m) => m.name).filter((n) => PW.chosen.has(n));
    const editing = PW.editing;
    const dropped = editing ? [...PW.was].filter((n) => !PW.chosen.has(n)) : [];
    if (dropped.length && !confirm(
        `${dropped.join(', ')} aus dem Projekt nehmen? Die Spuren dieser `
        + 'Modelle werden mit allem gelöscht, was darauf liegt.')) return;

    const wasOpen = PW.isOpen;
    pwClose();
    const answer = await post(editing ? '/api/project/edit' : '/api/project/new',
                              {name, models, dir: typeof editing === 'string' ? editing : null});
    if (!answer.ok) return toast(answer.error, 'err', 10000);
    await loadProjects();
    // A closed project answers with no payload: nothing was opened, and drawing
    // one would put a show on screen that nobody asked for.
    if (answer.project) applyProject(answer.project);
    if (editing) {
      toast(`Projekt „${name}“ geändert${wasOpen ? '' : ' — es ist nicht geöffnet'}.`,
            'ok', 3500);
    } else {
      // Straight into the timeline: creating a show and then having to find it
      // in a list is a step that answers nothing.
      showView('show');
      toast(`Projekt „${name}“ angelegt und geöffnet.`, 'ok', 4000);
    }
  };
}

document.addEventListener('DOMContentLoaded', pwBind);
