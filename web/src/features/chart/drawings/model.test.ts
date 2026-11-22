// Unit tests for the drawing model (run: npm run test:unit; Node's built-in test runner).
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  commit,
  createDrawing,
  deserialize,
  fibLevels,
  hitTest,
  historyInit,
  measure,
  moveDrawing,
  moveHandle,
  type Point,
  type Projector,
  redo,
  serialize,
  undo,
} from "./model.ts";

// 1 second of chart time = 1 px, 1 price unit = 1 px (y grows downwards).
const project: Projector = (pt: Point) => ({ x: pt.t, y: 1000 - pt.p });
const WIDTH = 800;

describe("createDrawing", () => {
  it("keeps the points and gives each drawing its own id", () => {
    const a = createDrawing("trend", [
      { t: 10, p: 900 },
      { t: 110, p: 800 },
    ]);
    const b = createDrawing("trend", [
      { t: 10, p: 900 },
      { t: 110, p: 800 },
    ]);
    assert.equal(a.kind, "trend");
    assert.deepEqual(a.points, [
      { t: 10, p: 900 },
      { t: 110, p: 800 },
    ]);
    assert.notEqual(a.id, b.id);
  });

  it("rejects the wrong number of points", () => {
    assert.throws(() => createDrawing("trend", [{ t: 1, p: 1 }]));
    assert.throws(() =>
      createDrawing("hline", [
        { t: 1, p: 1 },
        { t: 2, p: 2 },
      ]),
    );
  });

  it("rounds prices to whole units", () => {
    const d = createDrawing("hline", [{ t: 5, p: 123.6 }]);
    assert.equal(d.points[0].p, 124);
  });
});

describe("moving", () => {
  const line = createDrawing("trend", [
    { t: 10, p: 900 },
    { t: 110, p: 800 },
  ]);

  it("moves every point and leaves the original unchanged", () => {
    const moved = moveDrawing(line, 5, -20);
    assert.deepEqual(moved.points, [
      { t: 15, p: 880 },
      { t: 115, p: 780 },
    ]);
    assert.equal(line.points[0].t, 10);
    assert.equal(moved.id, line.id);
  });

  it("moves one handle", () => {
    const moved = moveHandle(line, 1, { t: 200, p: 700 });
    assert.deepEqual(moved.points[0], { t: 10, p: 900 });
    assert.deepEqual(moved.points[1], { t: 200, p: 700 });
  });
});

describe("hitTest", () => {
  it("finds a trend line near the segment but not beyond its ends", () => {
    const d = createDrawing("trend", [
      { t: 100, p: 900 },
      { t: 300, p: 900 },
    ]); // y = 100 from x 100 to 300
    assert.equal(hitTest(d, project, 200, 103, WIDTH).hit, true);
    assert.equal(hitTest(d, project, 200, 120, WIDTH).hit, false);
    assert.equal(hitTest(d, project, 400, 100, WIDTH).hit, false);
  });

  it("finds a ray beyond its second point but not before its first", () => {
    const d = createDrawing("ray", [
      { t: 100, p: 900 },
      { t: 300, p: 900 },
    ]);
    assert.equal(hitTest(d, project, 700, 101, WIDTH).hit, true);
    assert.equal(hitTest(d, project, 50, 100, WIDTH).hit, false);
  });

  it("finds a horizontal line anywhere across the chart", () => {
    const d = createDrawing("hline", [{ t: 100, p: 500 }]); // y = 500
    assert.equal(hitTest(d, project, 10, 504, WIDTH).hit, true);
    assert.equal(hitTest(d, project, 790, 495, WIDTH).hit, true);
    assert.equal(hitTest(d, project, 10, 520, WIDTH).hit, false);
  });

  it("finds a rectangle inside it", () => {
    const d = createDrawing("rect", [
      { t: 100, p: 900 },
      { t: 300, p: 700 },
    ]); // x 100..300, y 100..300
    assert.equal(hitTest(d, project, 200, 200, WIDTH).hit, true);
    assert.equal(hitTest(d, project, 350, 200, WIDTH).hit, false);
  });

  it("finds a Fibonacci level line", () => {
    const d = createDrawing("fib", [
      { t: 100, p: 900 },
      { t: 300, p: 700 },
    ]); // level 0.5 at y 200
    assert.equal(hitTest(d, project, 500, 201, WIDTH).hit, true);
    assert.equal(hitTest(d, project, 500, 215, WIDTH).hit, false);
  });

  it("reports the handle under the pointer", () => {
    const d = createDrawing("trend", [
      { t: 100, p: 900 },
      { t: 300, p: 800 },
    ]);
    assert.deepEqual(hitTest(d, project, 301, 199, WIDTH), { hit: true, handle: 1 });
    assert.deepEqual(hitTest(d, project, 99, 101, WIDTH), { hit: true, handle: 0 });
    assert.equal(hitTest(d, project, 200, 150, WIDTH).handle, null);
  });

  it("finds a text note inside its label box", () => {
    const d = createDrawing("text", [{ t: 100, p: 900 }], { text: "Asian low" });
    assert.equal(hitTest(d, project, 120, 95, WIDTH).hit, true);
    assert.equal(hitTest(d, project, 120, 160, WIDTH).hit, false);
  });
});

describe("fibLevels", () => {
  it("runs from the second point (0) back to the first point (1)", () => {
    const d = createDrawing("fib", [
      { t: 0, p: 1000 },
      { t: 10, p: 2000 },
    ]);
    const levels = fibLevels(d);
    assert.equal(levels[0].level, 0);
    assert.equal(levels[0].p, 2000);
    assert.equal(levels.find((l) => l.level === 0.5)?.p, 1500);
    assert.equal(levels.find((l) => l.level === 0.705)?.p, 1295);
    assert.equal(levels.at(-1)?.p, 1000);
  });
});

describe("measure", () => {
  it("reports units, pips, percent and candles", () => {
    // 5-digit FX: 1.08000 -> 1.08500 over 4 H1 candles.
    const m = measure({ t: 0, p: 108000 }, { t: 4 * 3600, p: 108500 }, 3600, 5);
    assert.equal(m.units, 500);
    assert.equal(m.pips, 50);
    assert.equal(m.bars, 4);
    assert.ok(Math.abs(m.percent - 0.463) < 0.001);
  });
});

describe("history", () => {
  const a = createDrawing("hline", [{ t: 1, p: 1 }]);
  const b = createDrawing("hline", [{ t: 2, p: 2 }]);

  it("undoes and redoes", () => {
    let h = historyInit([]);
    h = commit(h, [a]);
    h = commit(h, [a, b]);
    h = undo(h);
    assert.deepEqual(h.present, [a]);
    h = undo(h);
    assert.deepEqual(h.present, []);
    h = undo(h);
    assert.deepEqual(h.present, []);
    h = redo(h);
    assert.deepEqual(h.present, [a]);
  });

  it("clears redo after a new change", () => {
    let h = historyInit([]);
    h = commit(h, [a]);
    h = undo(h);
    h = commit(h, [b]);
    assert.equal(h.future.length, 0);
    assert.deepEqual(redo(h).present, [b]);
  });

  it("keeps at most 50 steps", () => {
    let h = historyInit([]);
    for (let i = 0; i < 60; i++) h = commit(h, [createDrawing("hline", [{ t: i, p: i }])]);
    assert.equal(h.past.length, 50);
  });
});

describe("serialize", () => {
  it("round-trips drawings, lock and hide", () => {
    const saved = {
      v: 1 as const,
      drawings: [createDrawing("text", [{ t: 1, p: 2 }], { text: "note" })],
      locked: true,
      hidden: false,
    };
    assert.deepEqual(deserialize(serialize(saved)), saved);
  });

  it("returns an empty chart for missing or broken data", () => {
    const empty = { v: 1, drawings: [], locked: false, hidden: false };
    assert.deepEqual(deserialize(null), empty);
    assert.deepEqual(deserialize("{not json"), empty);
    assert.deepEqual(deserialize(JSON.stringify({ v: 9, drawings: [1] })), empty);
  });

  it("drops drawings it does not understand", () => {
    const raw = JSON.stringify({
      v: 1,
      drawings: [
        {
          id: "a",
          kind: "trend",
          points: [
            { t: 1, p: 1 },
            { t: 2, p: 2 },
          ],
        },
        { id: "b", kind: "laser", points: [] },
        { id: "c", kind: "hline", points: [{ t: "x", p: 1 }] },
      ],
      locked: false,
      hidden: false,
    });
    assert.deepEqual(
      deserialize(raw).drawings.map((d) => d.id),
      ["a"],
    );
  });
});
