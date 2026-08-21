/* The airborne effect engine, ported to the browser.
 *
 * This is a line by line port of firmware/plane/src/effects.c -- same integer
 * arithmetic, same cue numbers, same phase maths. It exists so the interface
 * can show the pattern an aircraft will actually fly instead of asking anyone
 * to imagine "cue 6 at hue 200".
 *
 * Because it is a copy, it can drift. tools/ctest/effect_dump.c compiles the
 * real C and host/tests/test_effects_preview.py compares the two pixel for
 * pixel, so drift fails the test suite rather than the show.
 *
 * No DOM, no imports: a plain script that defines globals, loadable in node
 * for exactly that test.
 */

'use strict';

const EFFECT_COUNT = 11;

/* Gamma 2.2, the same table effects_init() builds.
 *
 * The preview does NOT use this by default, and that is deliberate. The table
 * exists because LEDs are linear and eyes are not, so a gamma corrected LED
 * *looks* like the linear value. A screen already applies its own correction,
 * so running the values through it a second time would only make the preview
 * darker than the real aircraft. The cross-check switches it on to compare
 * against the firmware byte for byte. */
const GAMMA = new Uint8Array(256);
for (let i = 0; i < 256; i++) GAMMA[i] = Math.floor((i / 255) ** 2.2 * 255 + 0.5);

/** Integer HSV with full saturation; hue walks the colour wheel in 0..255. */
function hsv(hue, value) {
  const sector = Math.floor(hue / 43);
  const offset = (hue - sector * 43) * 6;
  const q = (value * (255 - offset)) >> 8;
  const t = (value * offset) >> 8;
  switch (sector) {
    case 0:  return [value, t, 0];
    case 1:  return [q, value, 0];
    case 2:  return [0, value, t];
    case 3:  return [0, q, value];
    case 4:  return [t, 0, value];
    default: return [value, 0, q];
  }
}

const scale8 = (value, factor) => (value * factor) >> 8;

/** param 0..255 maps to a 2000 ms .. 100 ms cycle. */
const periodMs = (param) => 2000 - Math.floor(param * 1900 / 255);

/** Position inside the current cycle, 0..255. */
const phaseOf = (nowMs, period) => Math.floor((nowMs % period) * 256 / period);

/** Triangle wave, so fades go up and back down smoothly. */
const triangle = (x) => x < 128 ? x * 2 : (255 - x) * 2;

let randomState = 0x12345678;

/** The firmware's xorshift, bit for bit. */
function xorshift() {
  randomState ^= randomState << 13;
  randomState ^= randomState >>> 17;
  randomState ^= randomState << 5;
  randomState >>>= 0;
  return (randomState >>> 16) & 0xff;
}

/** Restarts the sparkle sequence. Only the cross-check needs this. */
function resetRandom(seed = 0x12345678) { randomState = seed >>> 0; }

/**
 * Renders one zone into a flat RGB array.
 *
 * `show` is {cue, hue, brightness, param}, 0..255 each, exactly as the four RC
 * channels carry them. Options: `max` is MAX_BRIGHTNESS, `out` reuses a buffer,
 * `gamma` applies the firmware's correction (see the note on GAMMA above).
 */
function renderEffect(show, nowMs, count, options = {}) {
  const max = options.max ?? 255;
  const pixels = options.out && options.out.length === count * 3
    ? options.out : new Uint8ClampedArray(count * 3);

  if (!show.cue || !show.brightness) {
    pixels.fill(0);
    return pixels;
  }

  const period = periodMs(show.param);
  const ph = phaseOf(nowMs, period);
  const base = hsv(show.hue, 255);
  const effect = show.cue >= EFFECT_COUNT ? 1 : show.cue;

  const put = (index, rgb) => {
    pixels[index * 3] = rgb[0];
    pixels[index * 3 + 1] = rgb[1];
    pixels[index * 3 + 2] = rgb[2];
  };
  const scaled = (rgb, level) =>
    [scale8(rgb[0], level), scale8(rgb[1], level), scale8(rgb[2], level)];
  const BLACK = [0, 0, 0];

  switch (effect) {
    case 1:                                            // solid
      for (let i = 0; i < count; i++) put(i, base);
      break;

    case 2: {                                          // breathe
      const colour = scaled(base, triangle(ph));
      for (let i = 0; i < count; i++) put(i, colour);
      break;
    }

    case 3: {                                          // strobe
      const on = ph < 24 ? base : BLACK;
      for (let i = 0; i < count; i++) put(i, on);
      break;
    }

    case 4: {                                          // double strobe
      const on = (ph < 16 || (ph >= 40 && ph < 56)) ? base : BLACK;
      for (let i = 0; i < count; i++) put(i, on);
      break;
    }

    case 5: {                                          // chase
      const head = (ph * count) >> 8;
      const width = Math.floor(count / 6) + 1;
      for (let i = 0; i < count; i++)
        put(i, ((i + count - head) % count) < width ? base : BLACK);
      break;
    }

    case 6: {                                          // comet with a tail
      const head = (ph * count) >> 8;
      for (let i = 0; i < count; i++) {
        const distance = (i + count - head) % count;
        let level = distance > 255 ? 0 : 255 - Math.floor(distance * 255 / count);
        level = scale8(level, level);
        put(i, scaled(base, level));
      }
      break;
    }

    case 7:                                            // sparkle
      for (let i = 0; i < count; i++) put(i, xorshift() < 24 ? base : BLACK);
      break;

    case 8:                                            // rainbow
      for (let i = 0; i < count; i++)
        put(i, hsv((show.hue + ph + Math.floor(i * 256 / count)) & 0xff, 255));
      break;

    case 9:                                            // police, hue ignored
      for (let i = 0; i < count; i++) {
        const front = i < Math.floor(count / 2);
        put(i, (front === (ph < 128)) ? [255, 0, 0] : [0, 0, 255]);
      }
      break;

    case 10: {                                         // theater chase
      const step = (ph * 3) >> 8;
      for (let i = 0; i < count; i++) put(i, i % 3 === step ? base : BLACK);
      break;
    }

    default:
      for (let i = 0; i < count; i++) put(i, base);
      break;
  }

  // finish(): the show dimmer, the safety ceiling, and gamma last.
  const level = scale8(show.brightness, max);
  for (let i = 0; i < pixels.length; i++) {
    const value = scale8(pixels[i], level);
    pixels[i] = options.gamma ? GAMMA[value] : value;
  }
  return pixels;
}

/** The slow amber pulse that means "no RC link". No cue produces this colour. */
function renderFailsafe(nowMs, count, options = {}) {
  const max = options.max ?? 255;
  const pixels = options.out && options.out.length === count * 3
    ? options.out : new Uint8ClampedArray(count * 3);

  const pulse = triangle(phaseOf(nowMs, 2000));
  const colour = [scale8(255, pulse), scale8(120, pulse), 0];
  // finish() runs on the failsafe pattern too, so the fixed level of 96 is
  // still scaled by the model's ceiling before it reaches the LEDs.
  const level = scale8(96, max);

  for (let i = 0; i < count; i++) {
    for (let c = 0; c < 3; c++) {
      const value = scale8(colour[c], level);
      pixels[i * 3 + c] = options.gamma ? GAMMA[value] : value;
    }
  }
  return pixels;
}

