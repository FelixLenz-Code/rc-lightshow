/* One WebGL canvas for every view of the model.
 *
 * The four flat views and the turnable one draw the same mesh; only the camera
 * differs -- four orthographic, one perspective on an orbit. That is the point
 * of doing it this way: before, the flat views were hand-drawn SVG and the 3D
 * view a separate mesh, so keeping the two in step was a promise rather than a
 * fact. Now a wing is in one place and every view is a photograph of it.
 *
 * Interaction stays out of here. The handles and grab lines live in an SVG
 * layer above the canvas, positioned through the same camera -- doing hit
 * testing in a shader would be a lot of machinery for two circles.
 */

let GL = null;            // context
let GL_SOLID = null;      // programme for the airframe
let GL_LIGHT = null;      // programme for the LEDs
let GL_MESH = null;       // the airframe, uploaded once
let GL_LEDS = null;       // rebuilt every frame
let GL_SPILL = 0;         // how many strip lights the shader was built for

/* What one lit LED throws onto the skin around it, as radiance. Chosen so a
 * wing under a full strip is clearly lit by it without the colour flattening
 * out -- which is the whole difference between a model with lamps stuck on and
 * a model flying its own light. */
const SPILL_PER_LED = 0.16;

/* How bright the night is, as a multiplier on everything that is not a strip.
 * Set from the slider in the toolbar: at the bottom the aeroplane is a
 * silhouette with its own lights on it, at the top it is lit well enough to
 * aim a strip at a particular rib. */
let GL_AMBIENT = 1;

const SOLID_VS = `
attribute vec3 aPos;
attribute vec3 aNormal;
attribute vec3 aColour;
uniform mat4 uProj;
uniform mat4 uView;
varying vec3 vNormal;
varying vec3 vColour;
varying vec3 vWorld;
void main() {
  // Nothing moves the mesh, so its own coordinates *are* world coordinates --
  // which is what the strip lights below are given in.
  vNormal = aNormal;
  vColour = aColour;
  vWorld = aPos;
  gl_Position = uProj * uView * vec4(aPos, 1.0);
}`;

/* The shading is the point of this window, not decoration.
 *
 * A show is flown after dark. Lit like a product photograph, a white model
 * drowns its own strips: 200 mW of LED cannot outshine a surface already at 80
 * per cent white, so every cue looked like faint dots on a bright aeroplane and
 * told you nothing about what it would look like in the air. So the only light
 * in the scene is a dim sky from above, an edge to keep the silhouette
 * readable -- and the strips themselves, which is the one light source that
 * really is there at night.
 *
 * All of it is added up in **linear light** and encoded to the screen at the
 * very end. That is not pedantry. Two lamps side by side are twice the light,
 * a lamp at twice the distance is a quarter of it, and neither of those is true
 * of the numbers a screen takes: sRGB is a curve, and adding along it makes two
 * dim lamps brighter than they should be and a distant one far too visible.
 * Doing the arithmetic straight in display values is what made the spill read
 * as a flat wash of paint rather than as light with a falloff.
 *
 * `SPILL` is baked in at compile time because GLSL ES wants constant loop
 * bounds, and it is chosen from what the driver will actually take.
 */
const solidFragment = (spill) => `
precision mediump float;
varying vec3 vNormal;
varying vec3 vColour;
varying vec3 vWorld;
uniform vec3 uEye;
uniform float uAmbient;
uniform int uSpillCount;
uniform vec3 uSpillPos[${spill}];
uniform vec3 uSpillCol[${spill}];
uniform vec3 uSpillDir[${spill}];

void main() {
  vec3 n = normalize(vNormal);
  vec3 toEye = normalize(uEye - vWorld);
  // The paint is given the way paint is written down, which is a screen value.
  // As a reflectance it has to be straightened out first.
  vec3 albedo = pow(vColour, vec3(2.2));

  // Night sky: cold and weak, and only from above. Squared, so a surface has
  // to face fairly well upwards before it catches any of it -- that difference
  // is what tells a wing top from a wing underside with no sun to do it.
  float up = n.y * 0.5 + 0.5;
  vec3 sky = mix(vec3(0.00035, 0.00046, 0.00080), vec3(0.0049, 0.0063, 0.0106),
                 up * up);
  float moon = max(dot(n, normalize(vec3(-0.35, 0.86, 0.36))), 0.0);
  // A floor under all of it. A flank faces neither sky nor ground and would
  // otherwise be exactly black, and you cannot aim a strip at a surface you
  // cannot see -- which is what these four views are for.
  vec3 ambient = sky + vec3(0.00097, 0.00114, 0.00166)
               + vec3(0.0040, 0.0046, 0.0060) * moon * moon;

  // A thin bright edge where the surface turns away. Without it a dark model
  // on a dark background has no outline at all.
  float rim = pow(1.0 - max(dot(n, toEye), 0.0), 3.5);
  ambient += vec3(0.013, 0.016, 0.023) * rim;
  ambient *= uAmbient;

  // What the strips throw back onto the aeroplane. This is the half of the
  // effect that makes the lights look attached rather than painted on: a red
  // wing tip puts red on the wing, and a strobe lights the whole flank for the
  // instant it fires.
  vec3 spill = vec3(0.0);
  for (int i = 0; i < ${spill}; i++) {
    if (i >= uSpillCount) break;
    vec3 d = vWorld - uSpillPos[i];
    float dist2 = max(dot(d, d), 1e-6);
    vec3 toHere = d * inversesqrt(dist2);
    // A strip lies flat on the skin and shines away from it, so nothing behind
    // that skin is lit: without this a strip on the belly lights the top of the
    // wing straight through the aeroplane carrying it.
    //
    // The test is how far the surface lies *past* the lamp's own plane, in
    // metres, not the angle to it. An angle would cut off the one surface the
    // lamp certainly does light -- the skin it is stuck to, which lies 13 mm
    // behind it and would come out at a full 180 degrees.
    float side = dot(d, uSpillDir[i]);
    float out_ = smoothstep(-0.07, -0.015, side);
    // Half Lambert: a lamp lying on the skin still washes what is beside it,
    // and a hard cosine would cut that off at exactly the wrong place.
    float face = max(dot(n, -toHere), 0.0) * 0.7 + 0.3;
    // Inverse square with a soft core, so a lamp 13 mm off the skin does not
    // divide by nothing directly underneath itself.
    spill += uSpillCol[i] * out_ * face / (1.0 + dist2 * 204.0);
  }

  vec3 col = albedo * (ambient + spill);
  // Rolled off rather than clipped: a strip at full tilt should whiten the skin
  // near it, not turn it into a flat patch of one colour.
  gl_FragColor = vec4(pow(col / (1.0 + col), vec3(1.0 / 2.2)), 1.0);
}`;

const LIGHT_VS = `
attribute vec3 aPos;
attribute vec2 aCorner;
attribute vec3 aColour;
attribute float aSize;
uniform mat4 uProj;
uniform mat4 uView;
varying vec2 vCorner;
varying vec3 vColour;
void main() {
  vColour = aColour;
  vCorner = aCorner;
  // Billboard: the quad is built in view space, so a lamp is a disc from every
  // angle rather than an ellipse that vanishes edge on.
  vec4 eye = uView * vec4(aPos, 1.0);
  eye.xy += aCorner * aSize;
  gl_Position = uProj * eye;
}`;

const LIGHT_FS = `
precision mediump float;
varying vec2 vCorner;
varying vec3 vColour;
void main() {
  float r = length(vCorner);
  if (r > 1.0) discard;
  // A hard core with a soft halo: what a small bright LED looks like through
  // a lens, and what makes a strobe read as a strobe.
  float core = smoothstep(0.44, 0.28, r);
  float halo = pow(max(0.0, 1.0 - r), 2.6) * 0.75;
  // The middle of a lamp you are looking straight at is past what the screen
  // can show, and the eye reads that as white however coloured the light is.
  // Kept to a third, though: this window exists to say what colour a cue is,
  // and a core washed all the way to white answers a different question.
  vec3 hot = mix(vColour, vec3(1.0), core * 0.34);
  // vColour is what the LED actually emits -- the byte the chain is fed is its
  // duty cycle, so it is already a linear quantity. The screen is not, so it
  // gets encoded here like everything else. Skipping this is what made a
  // half-lit strip look a quarter lit.
  gl_FragColor = vec4(pow(hot, vec3(1.0 / 2.2)), core + halo);
}`;

/* ------------------------------------------------------------------- setup */

function glInit(canvas) {
  GL = canvas.getContext('webgl2', {antialias: true, alpha: true})
    || canvas.getContext('webgl', {antialias: true, alpha: true});
  if (!GL) return false;

  // How many strip lights the airframe shader can carry. The floor WebGL
  // guarantees is small, so the count is taken from the driver rather than
  // assumed -- getting this wrong is a link failure and a black window.
  const room = GL.getParameter(GL.MAX_FRAGMENT_UNIFORM_VECTORS) || 16;
  GL_SPILL = Math.max(3, Math.min(24, Math.floor((room - 8) / 3)));
  GL_SOLID = glProgram(GL, SOLID_VS, solidFragment(GL_SPILL));
  GL_LIGHT = glProgram(GL, LIGHT_VS, LIGHT_FS);

  GL_MESH = {pos: GL.createBuffer(), nrm: GL.createBuffer(),
             col: GL.createBuffer(), count: 0};
  GL_LEDS = {
    pos: GL.createBuffer(), corner: GL.createBuffer(),
    col: GL.createBuffer(), size: GL.createBuffer(), count: 0,
  };
  glAirframe('motor');
  return true;
}

/* Puts one of the shapes on the graphics card. Cheap to call: it does nothing
 * unless the shape actually changed, which is how both the renderer and the
 * overlay can simply say which aircraft they want before every use. */
function glAirframe(kind) {
  if (!airframeUse(kind)) return false;
  if (!GL) return true;

  // Flat shading: every triangle gets its own copy of its vertices carrying the
  // face normal. Three times the data and none of the smoothing, which is what
  // a panelled airframe should look like.
  const pos = [], nrm = [], col = [];
  for (const face of AIRFRAME_3D) {
    const p = face.points;
    const u = [p[1][0] - p[0][0], p[1][1] - p[0][1], p[1][2] - p[0][2]];
    const v = [p[2][0] - p[0][0], p[2][1] - p[0][1], p[2][2] - p[0][2]];
    let n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
             u[0] * v[1] - u[1] * v[0]];
    const len = Math.hypot(...n) || 1;
    n = n.map((c) => c / len);
    const colour = face.colour.map((c) => c / 255);

    // A polygon of n points becomes a fan of n-2 triangles.
    for (let i = 1; i + 1 < p.length; i++) {
      for (const point of [p[0], p[i], p[i + 1]]) {
        pos.push(...point);
        nrm.push(...n);
        col.push(...colour);
      }
      if (face.twoSided) {
        // Drawn again the other way round, so a strut is never a hole.
        for (const point of [p[0], p[i + 1], p[i]]) {
          pos.push(...point);
          nrm.push(-n[0], -n[1], -n[2]);
          col.push(...colour);
        }
      }
    }
  }
  for (const [buffer, data] of [[GL_MESH.pos, pos], [GL_MESH.nrm, nrm],
                               [GL_MESH.col, col]]) {
    GL.bindBuffer(GL.ARRAY_BUFFER, buffer);
    GL.bufferData(GL.ARRAY_BUFFER, new Float32Array(data), GL.STATIC_DRAW);
  }
  GL_MESH.count = pos.length / 3;
  return true;
}

/* ----------------------------------------------------------------- cameras */

/* How much of the canvas a flat view's window gets: letterboxed, so a
 * placement means the same thing whatever the window size. That is what lets a
 * coordinate survive being saved. */
function flatFit(box, w, h) {
  const uSpan = box.u[1] - box.u[0];
  const vSpan = box.v[1] - box.v[0];
  const scale = Math.min(w / uSpan, h / vSpan) * 0.94;   // a little air
  return {scale, uMid: (box.u[0] + box.u[1]) / 2, vMid: (box.v[0] + box.v[1]) / 2};
}

/* Projection and view for whichever way the model is being looked at. */
function glCamera(view, w, h) {
  if (view === '3d') {
    const eye = [Math.sin(YAW) * Math.cos(PITCH) * DIST,
                 Math.sin(PITCH) * DIST + 0.12,
                 Math.cos(YAW) * Math.cos(PITCH) * DIST];
    return {eye, proj: mat4.perspective(0.72, w / h, 0.1, 40),
            view: mat4.lookAt(eye, [0, 0.06, 0.16], [0, 1, 0])};
  }

  const box = FLAT_VIEWS[view];
  const {scale, uMid, vMid} = flatFit(box, w, h);
  // The centre of the window, back in model space.
  const centre = [box.right[0] * uMid + box.up[0] * vMid,
                  box.right[1] * uMid + box.up[1] * vMid,
                  box.right[2] * uMid + box.up[2] * vMid];
  const eye = [centre[0] + box.back[0] * 10,
               centre[1] + box.back[1] * 10,
               centre[2] + box.back[2] * 10];
  return {
    eye,
    proj: mat4.ortho(-w / scale / 2, w / scale / 2,
                     -h / scale / 2, h / scale / 2, 0.1, 40),
    // lookAt works out the screen axes from eye and up, so `right` above is a
    // statement of intent that this cross-checks rather than a second source.
    view: mat4.lookAt(eye, centre, box.up),
  };
}

/* Where a placement lands on the canvas, in CSS pixels. The overlay uses this
 * so the handles sit exactly on the lights they belong to. */
function glProjectFlat(view, u, v, w, h) {
  const box = FLAT_VIEWS[view];
  const {scale, uMid, vMid} = flatFit(box, w, h);
  const {su, sv} = viewToScreen(box, u, v);
  return {x: w / 2 + (su - uMid) * scale, y: h / 2 - (sv - vMid) * scale};
}

/* And back again, for the mouse. */
function glUnprojectFlat(view, x, y, w, h) {
  const box = FLAT_VIEWS[view];
  const {scale, uMid, vMid} = flatFit(box, w, h);
  const su = (x - w / 2) / scale + uMid;
  const sv = -(y - h / 2) / scale + vMid;
  return {
    u: (su - box.u[0]) / (box.u[1] - box.u[0]),
    v: (box.v[1] - sv) / (box.v[1] - box.v[0]),
  };
}

/* ---------------------------------------------------------------- drawing */

function glDraw(view, frames) {
  const canvas = $('mock-gl');
  if (!GL || canvas.offsetParent === null) return;
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * ratio)) {
    canvas.width = Math.round(w * ratio);
    canvas.height = Math.round(h * ratio);
  }
  GL.viewport(0, 0, canvas.width, canvas.height);
  GL.clearColor(0, 0, 0, 0);
  GL.clear(GL.COLOR_BUFFER_BIT | GL.DEPTH_BUFFER_BIT);
  GL.enable(GL.DEPTH_TEST);
  GL.disable(GL.BLEND);

  // Whatever shape the chosen model is. Asked every frame because the model
  // can be changed from the list without anything else noticing.
  if (glAirframe(mockKind())) mockViewHome();

  const camera = glCamera(view, w, h);
  // The lamps are worked out first because the airframe is lit by them: at
  // night they are most of the light there is.
  const lamps = glLamps(view, frames);

  GL.useProgram(GL_SOLID.program);
  const u = GL_SOLID.uniforms;
  GL.uniformMatrix4fv(u.uProj, false, camera.proj);
  GL.uniformMatrix4fv(u.uView, false, camera.view);
  GL.uniform3fv(u.uEye, camera.eye);
  GL.uniform1f(u.uAmbient, GL_AMBIENT);
  GL.uniform1i(u.uSpillCount, lamps.spillCount);
  if (lamps.spillCount) {
    // An array uniform answers to its plain name on some drivers and to
    // `name[0]` on others; both are legal, so ask for whichever came back.
    GL.uniform3fv(u.uSpillPos || u['uSpillPos[0]'], lamps.spillPos);
    GL.uniform3fv(u.uSpillCol || u['uSpillCol[0]'], lamps.spillCol);
    GL.uniform3fv(u.uSpillDir || u['uSpillDir[0]'], lamps.spillDir);
  }
  glAttrib(GL, GL_MESH.pos, GL_SOLID.at.aPos, 3, 0, 0);
  glAttrib(GL, GL_MESH.nrm, GL_SOLID.at.aNormal, 3, 0, 0);
  glAttrib(GL, GL_MESH.col, GL_SOLID.at.aColour, 3, 0, 0);
  GL.drawArrays(GL.TRIANGLES, 0, GL_MESH.count);

  glPaintLamps(view, camera, lamps);
}

/* Every pixel of every placed segment, as billboard corners -- and the same
 * pixels again, boiled down to a handful of lights for the airframe shader.
 *
 * Both come out of one pass because both need the rendered frame, and reading
 * it twice would be the second place the two could disagree.
 */
function glLamps(view, frames) {
  const empty = {count: 0, spillCount: 0};
  const model = mockModel();
  if (!model) return empty;

  const here = mockSegments(model).filter((entry) => entry.place
    && (view === '3d' || entry.place.view === view));
  if (!here.length) return empty;

  const pos = [], corner = [], col = [], size = [];
  const spillPos = [], spillCol = [], spillDir = [];
  const CORNERS = [[-1, -1], [1, -1], [1, 1], [-1, -1], [1, 1], [-1, 1]];
  // Scaled to the shape: the same lamp on a quadcopter and on a glider has to
  // come out the same size on screen, and those two are three times apart.
  const radius = AIRFRAME_REACH * (view === '3d' ? 0.0235 : 0.031);
  // The budget shared out evenly: thirty lamps on one wing are one wash of
  // colour a few centimetres above the skin, and six samples of it look the
  // same as thirty at a fraction of the arithmetic.
  const perSegment = Math.max(1, Math.min(6, Math.floor(GL_SPILL / here.length)));

  for (const entry of here) {
    const p = entry.place;
    const pixels = chainPixels(entry.chain, frames.get(model.name));
    const seg = entry.segment;
    // Every pixel on the skin under it, not two ends and a straight line
    // between: see `liftStrip`.
    const line = liftStrip(p.view, p.x1, p.y1, p.x2, p.y2, seg.count);
    // Which way this strip faces: the axis its own view looks down. A strip
    // placed from above shines up, one placed from the left shines left.
    const facing = FLAT_VIEWS[p.view].back;
    // One accumulator per bucket: summed position, summed colour, how many.
    const buckets = Array.from({length: perSegment},
                               () => [0, 0, 0, 0, 0, 0, 0]);

    for (let i = 0; i < seg.count; i++) {
      const t = seg.count === 1 ? 0.5 : i / (seg.count - 1);
      const point = line[i];
      const at = (seg.start + i) * 3;
      const r = pixels[at] / 255, g = pixels[at + 1] / 255, bl = pixels[at + 2] / 255;
      const lit = r || g || bl;
      for (const [cx, cy] of CORNERS) {
        pos.push(...point);
        corner.push(cx, cy);
        // An LED that is off is a bead on the strip, not a lamp. It has to be
        // visible enough to show where the strip runs and dim enough that
        // thirty of them do not out-glow the one that is actually lit.
        // An LED that is off is a bead on the strip, not a lamp. Given in the
        // same linear units as a lit one, so the encode at the end treats them
        // alike -- it has to show where the strip runs and stay far enough
        // down that thirty beads do not out-glow the one that is lit.
        col.push(lit ? r : 0.010, lit ? g : 0.011, lit ? bl : 0.014);
        size.push(lit ? radius : radius * 0.5);
      }
      const bucket = buckets[Math.min(perSegment - 1,
                                      Math.floor(t * perSegment))];
      bucket[0] += point[0]; bucket[1] += point[1]; bucket[2] += point[2];
      bucket[3] += r; bucket[4] += g; bucket[5] += bl;
      bucket[6]++;
    }

    for (const bucket of buckets) {
      if (!bucket[6] || spillPos.length / 3 >= GL_SPILL) continue;
      const n = bucket[6];
      spillPos.push(bucket[0] / n, bucket[1] / n, bucket[2] / n);
      spillDir.push(facing[0], facing[1], facing[2]);
      // Summed, not averaged: a bucket stands in for the lamps in it, so ten
      // LEDs throw twice what five do. Averaging would make the wash depend on
      // how the budget happened to be divided up, and the same aeroplane would
      // change brightness the moment a second strip was placed on it.
      spillCol.push(bucket[3] * SPILL_PER_LED, bucket[4] * SPILL_PER_LED,
                    bucket[5] * SPILL_PER_LED);
    }
  }

  return {
    count: pos.length / 3, pos, corner, col, size,
    spillCount: spillPos.length / 3,
    spillPos: new Float32Array(spillPos), spillCol: new Float32Array(spillCol),
    spillDir: new Float32Array(spillDir),
  };
}

function glPaintLamps(view, camera, lamps) {
  if (!lamps.count) return;

  GL.bindBuffer(GL.ARRAY_BUFFER, GL_LEDS.pos);
  GL.bufferData(GL.ARRAY_BUFFER, new Float32Array(lamps.pos), GL.DYNAMIC_DRAW);
  GL.bindBuffer(GL.ARRAY_BUFFER, GL_LEDS.corner);
  GL.bufferData(GL.ARRAY_BUFFER, new Float32Array(lamps.corner), GL.DYNAMIC_DRAW);
  GL.bindBuffer(GL.ARRAY_BUFFER, GL_LEDS.col);
  GL.bufferData(GL.ARRAY_BUFFER, new Float32Array(lamps.col), GL.DYNAMIC_DRAW);
  GL.bindBuffer(GL.ARRAY_BUFFER, GL_LEDS.size);
  GL.bufferData(GL.ARRAY_BUFFER, new Float32Array(lamps.size), GL.DYNAMIC_DRAW);

  GL.useProgram(GL_LIGHT.program);
  GL.uniformMatrix4fv(GL_LIGHT.uniforms.uProj, false, camera.proj);
  GL.uniformMatrix4fv(GL_LIGHT.uniforms.uView, false, camera.view);
  glAttrib(GL, GL_LEDS.pos, GL_LIGHT.at.aPos, 3, 0, 0);
  glAttrib(GL, GL_LEDS.corner, GL_LIGHT.at.aCorner, 2, 0, 0);
  glAttrib(GL, GL_LEDS.col, GL_LIGHT.at.aColour, 3, 0, 0);
  glAttrib(GL, GL_LEDS.size, GL_LIGHT.at.aSize, 1, 0, 0);

  // Added rather than blended: light falling on light gets brighter, which is
  // what two strips crossing actually do.
  GL.enable(GL.BLEND);
  GL.blendFunc(GL.SRC_ALPHA, GL.ONE);
  // A flat view shows one view's strips and nothing else, so there is nothing
  // for them to hide behind: hiding them would only ever be the aeroplane
  // eating its own strip, which is what the skin search exists to prevent and
  // this makes impossible. The turnable view keeps the test, because there a
  // strip on the belly really is behind the wing.
  if (view !== '3d') GL.disable(GL.DEPTH_TEST);
  GL.depthMask(false);
  GL.drawArrays(GL.TRIANGLES, 0, lamps.count);
  GL.depthMask(true);
  GL.enable(GL.DEPTH_TEST);
  GL.disable(GL.BLEND);
}
