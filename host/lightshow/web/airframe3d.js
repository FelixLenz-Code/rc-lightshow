/* The airframe as a solid: cross sections swept into a hull, not flat panels.
 *
 * The first version was nine rectangles in one grey. It read as an aeroplane
 * only if you already knew it was one, because nothing told the eye which way a
 * surface faced. What fixes that is not more polygons but **shading**: a face
 * normal against a light direction, so a round fuselage looks round. Everything
 * here exists to give every face a normal worth shading.
 *
 * Three shapes, not one. A strip along a glider's wing and a strip along a
 * quadcopter's arm are different pictures, and a preview that draws both as a
 * Cessna answers a question nobody asked. Which shape a model gets is a
 * question in the wizard and a word in show.yaml; nothing airborne reads it.
 *
 * Built rather than downloaded. A model off the internet would have to be
 * fitted to the stations below anyway -- they are what makes the 3D view agree
 * with the four flat ones -- and it would arrive with a loader, a licence and a
 * few thousand triangles that canvas 2D cannot paint at sixty frames a second.
 *
 * Units: x across the span (positive to the right wing), y up, z from nose
 * (negative) to tail (positive).
 */

const RING = 12;                   // points around each fuselage section

/* A lens, thickest a third of the way back -- enough of an aerofoil that a wing
 * looks like a wing from every angle. */
const CHORD = [0, 0.08, 0.20, 0.38, 0.60, 0.80, 1];
const THICK = [0.02, 0.62, 0.95, 1.00, 0.78, 0.44, 0.02];

const SKIN = [206, 214, 226];      // the paint, before the light touches it
const DARK = [120, 130, 146];      // underside and inside surfaces
const GLASS = [96, 130, 170];
const SPINNER = [70, 78, 92];
const METAL = [96, 104, 118];

/* ------------------------------------------------------------------ pieces */

/* A hull swept through cross sections: station, half width, half height,
 * centre height. The table is the shape -- read it as a side view and a top
 * view at once. */
function bodyMesh(sections, {cap = true, nose = null} = {}) {
  const faces = [];
  const ringAt = (index) => {
    const [z, hw, hh, cy] = sections[index];
    return Array.from({length: RING}, (_, k) => {
      const a = (k / RING) * Math.PI * 2;
      return [Math.sin(a) * hw, cy + Math.cos(a) * hh, z];
    });
  };

  let previous = ringAt(0);
  for (let i = 1; i < sections.length; i++) {
    const current = ringAt(i);
    for (let k = 0; k < RING; k++) {
      const n = (k + 1) % RING;
      // Wound so the cross product of the first two edges points *away* from
      // the centre line. Round the other way the whole hull is lit from inside
      // and reads as a dark hole with bright wings around it.
      faces.push({points: [previous[k], current[k], current[n], previous[n]],
                  colour: nose !== null && sections[i][0] < nose ? SPINNER : SKIN});
    }
    previous = current;
  }
  // Tail cap, so the hull is closed and nothing shows through it.
  if (cap) faces.push({points: previous.slice().reverse(), colour: DARK});
  return faces;
}

/* One aerofoil surface swept from root to tip, plus the tip cap. `sign` is
 * which wing, `flat` lays it horizontally (a wing) or vertically (a fin). */
function foilMesh({rootLE, rootChord, tipLE, tipChord, span, rootY, tipY,
                   thickness, flat = true, sign = 1, colour = SKIN}) {
  const faces = [];
  // A fin is the same sweep turned on its side.
  const point = (t, k, side) => {
    const le = rootLE + (tipLE - rootLE) * t;
    const chord = rootChord + (tipChord - rootChord) * t;
    const z = le + chord * CHORD[k];
    const half = thickness * (1 - 0.35 * t) * THICK[k] * side;
    const y = rootY + (tipY - rootY) * t;
    return flat ? [span * t * sign, y + half, z] : [half, y, z];
  };

  // A left wing is a right wing sweeping the other way, so every face on it
  // comes out wound backwards. Turning them round here beats writing the
  // geometry twice -- and a wing lit from inside is exactly as dark as a
  // fuselage lit from inside.
  const add = (points, faceColour) => faces.push(
    {points: sign < 0 ? points.slice().reverse() : points, colour: faceColour});

  const steps = 6;
  for (let s = 0; s < steps; s++) {
    const t0 = s / steps, t1 = (s + 1) / steps;
    for (let k = 0; k < CHORD.length - 1; k++) {
      add([point(t0, k, 1), point(t0, k + 1, 1),
           point(t1, k + 1, 1), point(t1, k, 1)], colour);
      add([point(t1, k, -1), point(t1, k + 1, -1),
           point(t0, k + 1, -1), point(t0, k, -1)], flat ? DARK : colour);
    }
  }
  // Rounded-off tip: close the two surfaces against each other.
  for (let k = 0; k < CHORD.length - 1; k++) {
    add([point(1, k, 1), point(1, k + 1, 1),
         point(1, k + 1, -1), point(1, k, -1)], DARK);
  }
  return faces;
}

/* Wings come in pairs. */
const wingPair = (spec) => [...foilMesh({...spec, sign: -1}),
                            ...foilMesh({...spec, sign: 1})];

/* A closed tube between two points -- an arm, a leg, a motor can. */
function tubeMesh(from, to, radius, colour, sides = 10) {
  const axis = [to[0] - from[0], to[1] - from[1], to[2] - from[2]];
  const len = Math.hypot(...axis) || 1;
  const dir = axis.map((c) => c / len);
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
                           a[0] * b[1] - a[1] * b[0]];
  const norm = (v) => { const l = Math.hypot(...v) || 1; return v.map((c) => c / l); };
  // Any vector not along the axis gives a usable pair of cross axes.
  const ex = norm(cross(dir, Math.abs(dir[1]) > 0.9 ? [1, 0, 0] : [0, 1, 0]));
  const ey = cross(dir, ex);

  const ring = (at) => Array.from({length: sides}, (_, k) => {
    const a = (k / sides) * Math.PI * 2, c = Math.cos(a), s = Math.sin(a);
    return [at[0] + (ex[0] * c + ey[0] * s) * radius,
            at[1] + (ex[1] * c + ey[1] * s) * radius,
            at[2] + (ex[2] * c + ey[2] * s) * radius];
  });
  const a = ring(from), b = ring(to);
  const faces = [];
  for (let k = 0; k < sides; k++) {
    const n = (k + 1) % sides;
    faces.push({points: [a[k], b[k], b[n], a[n]], colour});
  }
  faces.push({points: a.slice().reverse(), colour: DARK});
  faces.push({points: b, colour: DARK});
  return faces;
}

/* A turning propeller is a blur, and a thin dark ring is what that looks like.
 * Anything more solid sits in front of the aircraft and hides it. */
function propMesh(centre, radius, axis = 'z') {
  return Array.from({length: 24}, (_, k) => {
    const a0 = (k / 24) * Math.PI * 2, a1 = ((k + 1) / 24) * Math.PI * 2;
    const at = (a, r) => (axis === 'z'
      ? [centre[0] + Math.sin(a) * r, centre[1] + Math.cos(a) * r, centre[2]]
      : [centre[0] + Math.sin(a) * r, centre[1], centre[2] + Math.cos(a) * r]);
    return {twoSided: true, colour: [40, 45, 55],
            points: [at(a0, radius * 0.94), at(a1, radius * 0.94),
                     at(a1, radius), at(a0, radius)]};
  });
}

/* A wheel: a short tube across the direction of travel, plus its faces. Two
 * sided, so the far half of the tube is not a hole. */
function wheelMesh(at, radius, width) {
  const faces = [];
  const ring = Array.from({length: 10}, (_, k) => {
    const a = (k / 10) * Math.PI * 2;
    return [at[0], at[1] + Math.sin(a) * radius, at[2] + Math.cos(a) * radius];
  });
  for (let k = 0; k < ring.length; k++) {
    const n = (k + 1) % ring.length;
    faces.push({twoSided: true, colour: [46, 50, 58], points: [
      ring[k], ring[n],
      [ring[n][0] + width, ring[n][1], ring[n][2]],
      [ring[k][0] + width, ring[k][1], ring[k][2]]]});
  }
  faces.push({twoSided: true, colour: [58, 63, 72], points: ring});
  return faces;
}

/* Which part of the aircraft a face belongs to. Not decoration: it is what
 * lets `skinOffset` below answer "what would a strip stuck on here lie on",
 * and the answer differs per view -- from above a wing is skin, from the side
 * it is something sticking out beyond the fuselage. */
const part = (name, faces) => faces.map((face) => ({...face, part: name}));

/* -------------------------------------------------------------- the shapes */

/* A powered aeroplane: high wing, tractor propeller, fixed undercarriage. */
function motorAirframe() {
  const M = {wingLE: -0.40, wingY: 0.24, halfSpan: 1.42, finTop: 0.78,
             finFront: 0.92, tailSpan: 0.52, tailZ: 1.12,
             bodyBottom: -0.20, halfWidth: 0.18};
  const sections = [
    [-1.000, 0.020, 0.020, 0.020],   // spinner tip
    [-0.940, 0.070, 0.070, 0.015],
    [-0.860, 0.130, 0.135, 0.010],   // cowling
    [-0.760, 0.165, 0.180, 0.005],
    [-0.600, 0.180, 0.215, 0.000],
    [-0.400, 0.185, 0.225, 0.000],   // cabin
    [-0.150, 0.180, 0.215, 0.000],
    [ 0.150, 0.150, 0.175, 0.010],
    [ 0.500, 0.115, 0.130, 0.025],
    [ 0.900, 0.080, 0.090, 0.038],
    [ 1.200, 0.055, 0.065, 0.045],
    [ 1.360, 0.040, 0.050, 0.050],   // where the fin meets it
  ];

  // Windscreen and side glazing, low enough to sit under the wing.
  const z0 = -0.62, z1 = -0.30, top = 0.235, w = 0.150;
  const canopy = [
    {points: [[-w, 0.10, z0], [w, 0.10, z0], [w * 0.8, top, z0 + 0.14],
              [-w * 0.8, top, z0 + 0.14]], colour: GLASS},
    {points: [[-w * 0.8, top, z0 + 0.14], [-w, 0.10, z0],
              [-w, 0.10, z1], [-w * 0.85, top, z1]], colour: GLASS},
    {points: [[w, 0.10, z0], [w * 0.8, top, z0 + 0.14],
              [w * 0.85, top, z1], [w, 0.10, z1]], colour: GLASS},
    {points: [[-w * 0.8, top, z0 + 0.14], [w * 0.8, top, z0 + 0.14],
              [w * 0.85, top, z1], [-w * 0.85, top, z1]], colour: GLASS},
  ];

  const gear = [];
  for (const x of [-0.42, 0.42]) {
    const knee = [x * 0.35, -0.16, -0.28], foot = [x, -0.44, -0.30];
    // Marked two sided: a strut this thin is one quad, and a quad seen from
    // behind would be culled away -- the leg would vanish at half the angles.
    gear.push({twoSided: true, colour: DARK, points: [
      [knee[0] - 0.02, knee[1], knee[2] - 0.03],
      [knee[0] + 0.02, knee[1], knee[2] + 0.03],
      [foot[0] + 0.02, foot[1], foot[2] + 0.03],
      [foot[0] - 0.02, foot[1], foot[2] - 0.03]]});
    gear.push(...wheelMesh(foot, 0.075, 0.035 * Math.sign(x)));
  }

  const faces = [
    ...part('body', bodyMesh(sections, {nose: -0.86})),
    ...part('canopy', canopy),
    ...part('wing', wingPair({rootLE: M.wingLE, rootChord: 0.42,
      tipLE: M.wingLE + 0.06, tipChord: 0.30, span: M.halfSpan,
      rootY: M.wingY, tipY: M.wingY + 0.06, thickness: 0.045})),
    ...part('tail', wingPair({rootLE: M.tailZ, rootChord: 0.24,
      tipLE: M.tailZ + 0.05, tipChord: 0.17, span: M.tailSpan,
      rootY: 0.055, tipY: 0.065, thickness: 0.024})),
    // The fin: the same sweep stood on end.
    ...part('fin', foilMesh({rootLE: M.finFront, rootChord: 0.44,
      tipLE: M.finFront + 0.26, tipChord: 0.20, span: 0,
      rootY: 0.05, tipY: M.finTop, thickness: 0.026, flat: false})),
    ...part('prop', propMesh([0, 0.02, -0.985], 0.42)),
    ...part('gear', gear),
  ];
  return {faces, reach: 1.62, views: flatViews({
    span: 1.62, nose: -1.20, tail: 1.58, high: 1.00, low: -0.66,
    topSkin: M.wingY + 0.075, bottomSkin: -(M.bodyBottom - 0.07),
    sideSkin: M.halfWidth + 0.07, hints: PLANE_HINTS,
  })};
}

/* A glider: no propeller, long thin wings, a slender boom and a T-tail. */
function seglerAirframe() {
  const M = {wingLE: -0.26, wingY: 0.16, halfSpan: 2.55, finTop: 0.62,
             finFront: 1.02, tailSpan: 0.42};
  const sections = [
    [-0.900, 0.018, 0.018, 0.010],   // the rounded nose of a glass ship
    [-0.850, 0.060, 0.062, 0.005],
    [-0.760, 0.098, 0.108, 0.000],
    [-0.600, 0.118, 0.140, 0.000],   // cockpit, the widest part
    [-0.400, 0.120, 0.148, 0.000],
    [-0.150, 0.110, 0.130, 0.005],
    [ 0.150, 0.082, 0.094, 0.015],
    [ 0.550, 0.055, 0.062, 0.028],   // the boom proper
    [ 0.950, 0.040, 0.045, 0.038],
    [ 1.250, 0.032, 0.036, 0.045],
    [ 1.420, 0.026, 0.030, 0.048],
  ];

  // One long blown canopy, which is most of what you see of a glider's nose.
  const canopy = [];
  const line = [[-0.80, 0.030, 0.030], [-0.66, 0.105, 0.108],
                [-0.48, 0.118, 0.120], [-0.30, 0.100, 0.096],
                [-0.18, 0.070, 0.055]];
  for (let i = 0; i + 1 < line.length; i++) {
    const [z0, w0, h0] = line[i], [z1, w1, h1] = line[i + 1];
    canopy.push({points: [[-w0, h0, z0], [w0, h0, z0], [w1, h1, z1], [-w1, h1, z1]],
                 colour: GLASS});
    canopy.push({twoSided: true, colour: GLASS,
                 points: [[-w0, h0, z0], [-w1, h1, z1], [-w1 * 0.9, 0.0, z1],
                          [-w0 * 0.9, 0.0, z0]]});
    canopy.push({twoSided: true, colour: GLASS,
                 points: [[w0 * 0.9, 0.0, z0], [w1 * 0.9, 0.0, z1],
                          [w1, h1, z1], [w0, h0, z0]]});
  }

  const faces = [
    ...part('body', bodyMesh(sections)),
    ...part('canopy', canopy),
    // High aspect ratio and a real taper: that is what makes it read as a
    // glider from above, before you have noticed the missing propeller.
    ...part('wing', wingPair({rootLE: M.wingLE, rootChord: 0.30,
      tipLE: M.wingLE + 0.15, tipChord: 0.13, span: M.halfSpan,
      rootY: M.wingY, tipY: M.wingY + 0.22, thickness: 0.030})),
    // A T-tail, sitting on top of the fin rather than on the boom.
    ...part('tail', wingPair({rootLE: M.finFront + 0.24, rootChord: 0.17,
      tipLE: M.finFront + 0.27, tipChord: 0.12, span: M.tailSpan,
      rootY: M.finTop, tipY: M.finTop, thickness: 0.016})),
    ...part('fin', foilMesh({rootLE: M.finFront, rootChord: 0.34,
      tipLE: M.finFront + 0.20, tipChord: 0.19, span: 0,
      rootY: 0.045, tipY: M.finTop, thickness: 0.020, flat: false})),
    // A single wheel half sunk into the belly: the whole undercarriage.
    ...part('gear', wheelMesh([0, -0.135, -0.20], 0.062, 0.030)),
  ];
  return {faces, reach: 2.75, views: flatViews({
    span: 2.75, nose: -1.10, tail: 1.62, high: 0.92, low: -0.50,
    topSkin: M.wingY + 0.06, bottomSkin: 0.24, sideSkin: 0.19,
    hints: GLIDER_HINTS,
  })};
}

/* A quadcopter: a body, four arms out to four motors, and legs under it. */
function quadAirframe() {
  const ARM = 0.78;                  // centre to motor
  const BODY_Y = 0.02;
  const sections = [
    [-0.42, 0.055, 0.045, BODY_Y],
    [-0.34, 0.150, 0.095, BODY_Y],
    [-0.10, 0.215, 0.135, BODY_Y],
    [ 0.14, 0.215, 0.135, BODY_Y],
    [ 0.36, 0.150, 0.100, BODY_Y],
    [ 0.44, 0.060, 0.050, BODY_Y],
  ];

  // The four arms, out to the corners. Same handedness as the aeroplanes: x to
  // the right, z to the rear, so the arm at the top left of the top view is
  // the front left one.
  const arms = [], pods = [], props = [], legs = [];
  for (const [sx, sz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
    const hub = [sx * 0.17, BODY_Y, sz * 0.17];
    const motor = [sx * ARM * 0.707, BODY_Y + 0.03, sz * ARM * 0.707];
    arms.push(...tubeMesh(hub, motor, 0.036, SKIN, 8));
    pods.push(...tubeMesh([motor[0], motor[1] - 0.02, motor[2]],
                          [motor[0], motor[1] + 0.055, motor[2]], 0.115, METAL, 12));
    props.push(...propMesh([motor[0], motor[1] + 0.075, motor[2]], 0.40, 'y'));
    // A leg under each arm, so the thing stands on something.
    legs.push(...tubeMesh([motor[0] * 0.62, BODY_Y - 0.02, motor[2] * 0.62],
                          [motor[0] * 0.72, -0.30, motor[2] * 0.72],
                          0.018, DARK, 6));
  }
  // A hood over the front half, which is what says which way it flies.
  const canopy = [
    {points: [[-0.13, 0.145, -0.30], [0.13, 0.145, -0.30],
              [0.15, 0.175, -0.10], [-0.15, 0.175, -0.10]], colour: GLASS},
    {points: [[-0.15, 0.175, -0.10], [0.15, 0.175, -0.10],
              [0.14, 0.170, 0.10], [-0.14, 0.170, 0.10]], colour: GLASS},
  ];

  const faces = [
    ...part('body', [...bodyMesh(sections), ...pods]),
    ...part('canopy', canopy),
    // The arms are the horizontal structure: for the placement views they play
    // exactly the part a wing plays on an aeroplane.
    ...part('wing', arms),
    ...part('prop', props),
    ...part('gear', legs),
  ];
  return {faces, reach: 0.80, views: flatViews({
    span: 0.80, nose: -0.80, tail: 0.80, high: 0.48, low: -0.42,
    topSkin: 0.20, bottomSkin: 0.22, sideSkin: 0.26,
    hints: QUAD_HINTS,
  })};
}

/* ------------------------------------------------------------- the cameras */

/* Five ways of looking at the one model.
 *
 * The four flat ones are orthographic -- a technical drawing, no vanishing
 * point. Each is described entirely in *screen* terms: which model axis runs
 * right, which runs up, how far the window reaches in each, and where the skin
 * is along the axis being looked down. Keeping model axes and screen axes apart
 * is the whole trick; mixing them is how a strip ends up beside the wing
 * instead of on it.
 *
 * That window is also the coordinate system a placement is stored in: `u` and
 * `v` from 0 to 1 across it, `v` counted from the top of the picture. Because
 * both the picture and the placement come from these numbers, the flat views
 * and the turnable one cannot drift apart. The window belongs to the shape, so
 * changing a model from aeroplane to quadcopter moves its placements with it
 * rather than leaving them at absolute millimetres that mean nothing any more.
 */
const PLANE_HINTS = {
  top: 'Nase oben. Die Fläche liegt über dem Rumpf; links im Bild ist die '
    + 'linke Fläche, so wie Du von hinten daraufschaust.',
  bottom: 'Nase oben, aber von unten gesehen — links im Bild ist jetzt die '
    + 'rechte Fläche. Das Fahrwerk zeigt, welche Ansicht das ist.',
  left: 'Nase links — die linke Rumpfseite, wie beim Vorbeiflug von links.',
  right: 'Nase rechts — die rechte Rumpfseite. Spiegelbild der linken.',
};

const GLIDER_HINTS = {
  top: 'Nase oben. Die lange schmale Fläche liegt über dem Rumpf; links im '
    + 'Bild ist die linke Fläche.',
  bottom: 'Von unten — links im Bild ist jetzt die rechte Fläche. Das einzelne '
    + 'Rad sitzt unter dem Schwerpunkt.',
  left: 'Nase links. Die Haube reicht weit nach vorn, das Höhenleitwerk sitzt '
    + 'oben auf der Finne.',
  right: 'Nase rechts. Spiegelbild der linken Seite.',
};

const QUAD_HINTS = {
  top: 'Von oben, Bug nach oben. Die vier Arme zeigen in die Ecken — links '
    + 'oben ist der vordere linke. Hier gehören die Streifen auf die Arme hin.',
  bottom: 'Von unten, Bug weiter oben — links im Bild ist jetzt der vordere '
    + 'rechte Arm. Die Beine zeigen zu Dir.',
  left: 'Von links, Bug links. Arme und Motoren stehen hier fast '
    + 'hintereinander — auf einen Arm zielst Du besser von oben.',
  right: 'Von rechts, Bug rechts.',
};

/* The four flat windows for one shape. Everything that differs between an
 * aeroplane and a quadcopter is a number in this call. */
function flatViews({span, nose, tail, high, low,
                    topSkin, bottomSkin, sideSkin, hints}) {
  return {
    top: {
      label: 'von oben', hint: hints.top,
      right: [1, 0, 0], up: [0, 0, -1], back: [0, 1, 0],
      u: [-span, span], v: [-tail, -nose],
      // Seen from above, wing and tailplane are skin you can glue a strip to.
      // The fin is not: it stands well above everything around it, and a spine
      // strip running back to the tail would climb it. You place on the fin
      // from the side, where it is a surface rather than a sliver.
      sticks: ['body', 'canopy', 'wing', 'tail'],
      skin: topSkin,
    },
    bottom: {
      label: 'von unten', hint: hints.bottom,
      right: [-1, 0, 0], up: [0, 0, -1], back: [0, -1, 0],
      u: [-span, span], v: [-tail, -nose],
      sticks: ['body', 'wing', 'tail'],
      skin: bottomSkin,
    },
    left: {
      label: 'von links', hint: hints.left,
      right: [0, 0, 1], up: [0, 1, 0], back: [-1, 0, 0],
      u: [nose, tail], v: [low, high],
      // From the side the wing reaches far out sideways, so taking the
      // outermost surface would fling a flank strip to the wing tip. A side
      // view means the fuselage and what stands on it.
      sticks: ['body', 'canopy', 'fin'],
      skin: sideSkin,
    },
    right: {
      label: 'von rechts', hint: hints.right,
      right: [0, 0, -1], up: [0, 1, 0], back: [1, 0, 0],
      u: [-tail, -nose], v: [low, high],
      sticks: ['body', 'canopy', 'fin'],
      skin: sideSkin,
    },
  };
}

/* ------------------------------------------------------------ which shape */

const AIRFRAMES = {
  motor: {label: 'Motorflugzeug', build: motorAirframe},
  segler: {label: 'Segelflugzeug', build: seglerAirframe},
  quad: {label: 'Quadrocopter', build: quadAirframe},
};

/* The one currently drawn. Everything below reads these rather than a fixed
 * table: the window shows one aircraft at a time, and switching model may
 * switch shape. */
let AIRFRAME_KIND = null;
let AIRFRAME_3D = [];
let FLAT_VIEWS = {};
let SKIN_TRIS = [];
/* How far the turnable view stands off. A fixed number would frame the shape
 * it was chosen for and nothing else: a quadcopter is a fifth of a glider
 * across, and at a glider's distance it is a speck. */
let AIRFRAME_DIST = 4.6;
/* Half the width of the shape, which is what anything drawn *on* it has to be
 * measured against -- a lamp is a lamp, but a quadcopter is a fifth of a glider
 * across and its lamps must not come out five times the size. */
let AIRFRAME_REACH = 1.62;

/* Selects a shape. Says whether anything changed, because the renderer keeps a
 * copy of the mesh on the graphics card and has to be told to replace it. */
function airframeUse(kind) {
  const key = AIRFRAMES[kind] ? kind : 'motor';
  if (key === AIRFRAME_KIND) return false;
  const built = AIRFRAMES[key].build();
  AIRFRAME_KIND = key;
  AIRFRAME_3D = built.faces;
  FLAT_VIEWS = built.views;
  AIRFRAME_REACH = built.reach;
  AIRFRAME_DIST = built.reach * 2.85;
  SKIN_TRIS = skinTriangles(built.faces);
  LIFT_CACHE.clear();
  return true;
}

/* The airframe as bare triangles with their bounding boxes, for the search. */
function skinTriangles(faces) {
  const out = [];
  for (const face of faces) {
    const p = face.points;
    for (let i = 1; i + 1 < p.length; i++) {
      const tri = [p[0], p[i], p[i + 1]];
      out.push({tri, part: face.part, bb: [
        Math.min(tri[0][0], tri[1][0], tri[2][0]),
        Math.min(tri[0][1], tri[1][1], tri[2][1]),
        Math.min(tri[0][2], tri[1][2], tri[2][2]),
        Math.max(tri[0][0], tri[1][0], tri[2][0]),
        Math.max(tri[0][1], tri[1][1], tri[2][1]),
        Math.max(tri[0][2], tri[1][2], tri[2][2])]});
    }
  }
  return out;
}

/* Screen coordinates of a placement, in the units the window is measured in.
 * `v` counts down from the top, the way a picture is read. */
function viewToScreen(box, u, v) {
  return {
    su: box.u[0] + (box.u[1] - box.u[0]) * u,
    sv: box.v[1] - (box.v[1] - box.v[0]) * v,
  };
}

/* And back. The window is not square, so anything geometric -- turning a strip,
 * measuring its length -- has to be done in these units and converted, or a
 * quarter turn comes out as a squash. */
function screenToView(box, su, sv) {
  return {
    u: (su - box.u[0]) / (box.u[1] - box.u[0]),
    v: (box.v[1] - sv) / (box.v[1] - box.v[0]),
  };
}

/* ---------------------------------------------------- finding the skin */

/* Every view axis is a signed unit axis, which is what makes the search below
 * cheap: no rotation, just a coordinate and a sign. */
const axisOf = (v) => {
  for (let i = 0; i < 3; i++) if (v[i]) return [i, v[i] > 0 ? 1 : -1];
  return [0, 1];
};

/* How far out along the view's own axis the aeroplane's surface is, under the
 * point (su, sv) of that view -- or null where the view looks straight past it.
 *
 * This is what stops a strip from being swallowed by the aircraft carrying it.
 * A wing has dihedral and an aerofoil section; a plane laid across it at one
 * fixed height is above the skin near the root and *below* it near the tip, so
 * the outer third of every wing strip used to be inside the wing, hidden by the
 * depth buffer. Asking the geometry instead means the pixels sit on the skin
 * wherever the skin happens to be, and follow the dihedral when the model is
 * turned.
 *
 * The ray runs along a coordinate axis, so there is no ray-triangle arithmetic
 * to do: two of the three coordinates are fixed, and the answer is the third,
 * interpolated across whichever triangles cover that point.
 */
function skinOffset(view, su, sv, sticks) {
  const box = FLAT_VIEWS[view];
  sticks = sticks || box.sticks;
  const [ri, rs] = axisOf(box.right);
  const [ui, us] = axisOf(box.up);
  const [bi, bs] = axisOf(box.back);
  const x = rs * su;               // the two coordinates the view pins down
  const y = us * sv;
  let best = null;

  for (const {tri, bb, part} of SKIN_TRIS) {
    if (!sticks.includes(part)) continue;
    if (x < bb[ri] || x > bb[ri + 3] || y < bb[ui] || y > bb[ui + 3]) continue;

    const ax = tri[0][ri], ay = tri[0][ui];
    const bx = tri[1][ri], by = tri[1][ui];
    const cx = tri[2][ri], cy = tri[2][ui];
    const den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy);
    if (Math.abs(den) < 1e-12) continue;         // edge on, covers no area
    const w0 = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / den;
    const w1 = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / den;
    const w2 = 1 - w0 - w1;
    if (w0 < 0 || w1 < 0 || w2 < 0) continue;

    // Nearest to the viewer wins: that is the surface you would be gluing to.
    const at = bs * (w0 * tri[0][bi] + w1 * tri[1][bi] + w2 * tri[2][bi]);
    if (best === null || at > best) best = at;
  }
  return best;
}

/* Clearance between skin and lamp: enough that the strip is never eaten by the
 * surface it lies on, little enough that it still reads as lying on it. */
const SKIN_CLEAR = 0.013;

/* Answers are reused: a placement holds still between drags, and the search
 * above walks every triangle for every pixel. Dropped wholesale once it grows
 * past a drag's worth of lines -- there is nothing worth ageing individually. */
const LIFT_CACHE = new Map();

/* Where the pixels of one placement sit in space.
 *
 * Two of the three coordinates come from the window, the third from the
 * airframe: something drawn on the top view lies on the upper surface,
 * something on the left view on the left flank. That is what a three-view
 * drawing means, and it is why the turnable model needs no numbers of its own.
 *
 * Every pixel finds its own skin. Lifting only the two ends and running a
 * straight line between them -- which is what this used to do -- works on a
 * wing, because a wing is nearly flat along the span. On a fuselage it does
 * not: a flank is a tube, widest under the wing and tapering to the tail, so
 * the chord between two points on it passes *through* the middle. Those pixels
 * were inside the aeroplane, and the depth buffer duly threw them away. A strip
 * along the side vanished in its middle and nowhere else.
 *
 * A tape does not do that. It lies on what it touches, bridges what it cannot
 * reach, and carries straight on past an edge -- which is exactly the profile
 * built below.
 */
function liftStrip(view, x1, y1, x2, y2, count) {
  const box = FLAT_VIEWS[view];
  if (!box) return Array.from({length: count}, () => [0, 0, 0]);

  const key = `${view}|${x1.toFixed(4)}|${y1.toFixed(4)}|${x2.toFixed(4)}`
            + `|${y2.toFixed(4)}|${count}`;
  const held = LIFT_CACHE.get(key);
  if (held) return held;
  if (LIFT_CACHE.size > 4000) LIFT_CACHE.clear();

  const su = new Float64Array(count), sv = new Float64Array(count);
  const raw = new Array(count);
  let first = -1, last = -1;
  for (let i = 0; i < count; i++) {
    const t = count === 1 ? 0.5 : i / (count - 1);
    const at = viewToScreen(box, x1 + (x2 - x1) * t, y1 + (y2 - y1) * t);
    su[i] = at.su;
    sv[i] = at.sv;
    raw[i] = skinOffset(view, at.su, at.sv);
    if (raw[i] !== null) { if (first < 0) first = i; last = i; }
  }

  const off = new Float64Array(count);
  if (first < 0) {
    // Nothing under any pixel -- the whole strip is off the aeroplane. The old
    // fixed plane is as good an answer as there is.
    off.fill(box.skin);
  } else {
    // Past either end there is no skin left to follow, so the tape keeps the
    // height it had when it ran off. Gaps in between are spanned straight.
    for (let i = 0; i < first; i++) off[i] = raw[first];
    for (let i = last + 1; i < count; i++) off[i] = raw[last];
    let anchor = first;
    off[first] = raw[first];
    for (let i = first + 1; i <= last; i++) {
      if (raw[i] === null) continue;
      const span = i - anchor;
      for (let k = 1; k < span; k++) {
        off[anchor + k] = raw[anchor] + (raw[i] - raw[anchor]) * (k / span);
      }
      off[i] = raw[i];
      anchor = i;
    }

    // Pulled taut. A tape cannot turn a right angle between two neighbouring
    // LEDs: where the skin steps -- off a trailing edge, over the side of a
    // fuselage -- it spans the step instead of diving into it. Run from both
    // ends, this only ever lifts a pixel, so no pixel is pushed under the skin
    // it was just placed on.
    const stepAlong = count > 1
      ? Math.hypot(su[count - 1] - su[0], sv[count - 1] - sv[0]) / (count - 1)
      : 0;
    const rise = Math.max(0.004, stepAlong * 0.7);
    for (let i = 1; i < count; i++) off[i] = Math.max(off[i], off[i - 1] - rise);
    for (let i = count - 2; i >= 0; i--) off[i] = Math.max(off[i], off[i + 1] - rise);
  }

  const out = new Array(count);
  for (let i = 0; i < count; i++) {
    const d = off[i] + SKIN_CLEAR;
    out[i] = [box.right[0] * su[i] + box.up[0] * sv[i] + box.back[0] * d,
              box.right[1] * su[i] + box.up[1] * sv[i] + box.back[1] * d,
              box.right[2] * su[i] + box.up[2] * sv[i] + box.back[2] * d];
  }
  LIFT_CACHE.set(key, out);
  return out;
}

/* Everything solid, for the question "is this point inside the aeroplane". The
 * undercarriage and the propeller disc are left out: they are things hanging in
 * the airstream, not a volume a strip could be buried in. */
const SOLID_PARTS = ['body', 'canopy', 'wing', 'tail', 'fin'];

/* How many pixels of a lifted strip ended up inside the airframe.
 *
 * Not every drawn line can carry a strip. On the side of the fuselage at the
 * height where the wing joins it there is no fuselage to lie on -- the wing
 * occupies that height, right through, and the same goes for the tailplane
 * root. A tape cannot go there on the real aeroplane either, so the picture
 * does not quietly bend it somewhere else; it counts those pixels and the
 * window says so.
 *
 * The test needs no new machinery. A point is inside if the highest skin over
 * it is higher and the lowest skin under it is lower -- and both of those are
 * the search the lift already does, taken once from above and once from below.
 */
function buriedPixels(points) {
  let n = 0;
  for (const p of points) {
    const above = skinOffset('top', p[0], -p[2], SOLID_PARTS);
    if (above === null || above < p[1]) continue;
    const below = skinOffset('bottom', -p[0], -p[2], SOLID_PARTS);
    if (below === null || -below > p[1]) continue;
    n++;
  }
  return n;
}
