/*
 * ui/dragonwave.js - the launch page's dragon, cut into moving parts.
 *
 * dragon.js ships one flat run of <rect> per state and says, at the top, not
 * to hand-edit it. So this takes the same sprite and slices it at load time
 * instead: the right wing comes out into its own group so it can flap, and the
 * eye block comes out twice, open from "idle" and shut from "asleep", so a
 * blink can swap between two real frames rather than fading a hole in the face.
 *
 * Everything here is rectangle arithmetic on the published sprite. Change the
 * art in dragon.js and this still works; it never assumes a particular pixel
 * is a particular colour, only which box it falls in.
 */

import { DRAGON_BODY } from "/dragon.js";

// The sprite is 22x22. These are the boxes we need to move independently,
// half-open in sprite units: [x0, x1) by [y0, y1).
const WING = { x0: 15, y0: 14, x1: 19, y1: 17 };
const EYES = [{ x0: 6, y0: 5, x1: 9, y1: 9 },
               { x0: 13, y0: 5, x1: 16, y1: 9 }];

const RECT = /<rect x="(-?[\d.]+)" y="(-?[\d.]+)" width="([\d.]+)" height="([\d.]+)" fill="(#[0-9A-Fa-f]+)"\/>/g;

function parse(markup) {
  const out = [];
  let m;
  RECT.lastIndex = 0;
  while ((m = RECT.exec(markup || "")) !== null) {
    out.push({ x: +m[1], y: +m[2], w: +m[3], h: +m[4], f: m[5] });
  }
  return out;
}

function emit(rects) {
  return rects.map(function (r) {
    return '<rect x="' + r.x + '" y="' + r.y + '" width="' + r.w +
           '" height="' + r.h + '" fill="' + r.f + '"/>';
  }).join("");
}

/* Split one rect against a box. The sprite is run-length merged along x, so a
 * single rect can straddle a box edge; returning the remainder rather than
 * taking the whole rect is what keeps the body from losing pixels. */
function cut(r, box) {
  const ix0 = Math.max(r.x, box.x0), ix1 = Math.min(r.x + r.w, box.x1);
  const iy0 = Math.max(r.y, box.y0), iy1 = Math.min(r.y + r.h, box.y1);
  if (ix0 >= ix1 || iy0 >= iy1) return { inside: [], outside: [r] };

  const outside = [];
  if (r.y < iy0) outside.push({ x: r.x, y: r.y, w: r.w, h: iy0 - r.y, f: r.f });
  if (r.y + r.h > iy1) outside.push({ x: r.x, y: iy1, w: r.w, h: r.y + r.h - iy1, f: r.f });
  if (r.x < ix0) outside.push({ x: r.x, y: iy0, w: ix0 - r.x, h: iy1 - iy0, f: r.f });
  if (r.x + r.w > ix1) outside.push({ x: ix1, y: iy0, w: r.x + r.w - ix1, h: iy1 - iy0, f: r.f });

  return { inside: [{ x: ix0, y: iy0, w: ix1 - ix0, h: iy1 - iy0, f: r.f }], outside: outside };
}

function partition(rects, boxes) {
  let rest = rects;
  const taken = [];
  boxes.forEach(function (box) {
    const next = [];
    rest.forEach(function (r) {
      const c = cut(r, box);
      taken.push.apply(taken, c.inside);
      next.push.apply(next, c.outside);
    });
    rest = next;
  });
  return { taken: taken, rest: rest };
}

/*
 * One <svg> with four groups:
 *   .d-body  everything that does not move
 *   .d-wing  the right wing, rotated by the wave animation
 *   .d-open  the eyes, open
 *   .d-shut  the same cells drawn from the sleeping frame, hidden until a blink
 *
 * The two eye groups cover identical cells, so a blink is one group swapping
 * for the other and never leaves a gap in the face.
 */
export function wavingDragon(cls) {
  const awake = parse(DRAGON_BODY.idle);
  const asleep = parse(DRAGON_BODY.asleep || DRAGON_BODY.idle);

  const wing = partition(awake, [WING]);
  const eyes = partition(wing.rest, EYES);
  const shut = partition(asleep, EYES).taken;

  return '<svg class="' + (cls || "") + '" viewBox="0 0 22 22" ' +
         'shape-rendering="crispEdges" xmlns="http://www.w3.org/2000/svg" ' +
         'aria-hidden="true">' +
         '<g class="d-body">' + emit(eyes.rest) + "</g>" +
         '<g class="d-shut">' + emit(shut) + "</g>" +
         '<g class="d-open">' + emit(eyes.taken) + "</g>" +
         '<g class="d-wing">' + emit(wing.taken) + "</g>" +
         "</svg>";
}

// Exported so the self-test can assert no pixel was lost or duplicated in the
// slicing, which is the one way this file can fail quietly.
export const WAVE_BOXES = { wing: WING, eyes: EYES };
export const _internals = { parse: parse, partition: partition, cut: cut };
