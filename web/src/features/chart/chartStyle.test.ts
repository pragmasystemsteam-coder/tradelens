// Unit tests for chart styles: Heikin Ashi and series data (npm run test:unit).
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { heikinAshi, seriesData } from "./chartStyle.ts";

const bars = [
  { time: 1, open: 10, high: 12, low: 9, close: 11 },
  { time: 2, open: 11, high: 14, low: 10, close: 13 },
  { time: 3, open: 13, high: 13, low: 8, close: 9 },
];

describe("heikinAshi", () => {
  it("averages each bar and chains the opens", () => {
    const ha = heikinAshi(bars);
    // bar 1: close (10+12+9+11)/4 = 10.5, open (10+11)/2 = 10.5
    assert.equal(ha[0].close, 10.5);
    assert.equal(ha[0].open, 10.5);
    assert.equal(ha[0].high, 12);
    assert.equal(ha[0].low, 9);
    // bar 2: open (10.5+10.5)/2 = 10.5, close (11+14+10+13)/4 = 12
    assert.equal(ha[1].open, 10.5);
    assert.equal(ha[1].close, 12);
    assert.equal(ha[1].high, 14);
    assert.equal(ha[1].low, 10);
    // bar 3: open (10.5+12)/2 = 11.25, close (13+13+8+9)/4 = 10.75
    assert.equal(ha[2].open, 11.25);
    assert.equal(ha[2].close, 10.75);
    assert.equal(ha[2].high, 13);
    assert.equal(ha[2].low, 8);
  });

  it("keeps times and handles an empty list", () => {
    assert.deepEqual(
      heikinAshi(bars).map((b) => b.time),
      [1, 2, 3],
    );
    assert.deepEqual(heikinAshi([]), []);
  });

  it("never puts the body outside the wick", () => {
    for (const b of heikinAshi(bars)) {
      assert.ok(b.high >= Math.max(b.open, b.close));
      assert.ok(b.low <= Math.min(b.open, b.close));
    }
  });
});

describe("seriesData", () => {
  it("uses closes for line and area", () => {
    assert.deepEqual(seriesData(bars, "line"), [
      { time: 1, value: 11 },
      { time: 2, value: 13 },
      { time: 3, value: 9 },
    ]);
    assert.deepEqual(seriesData(bars, "area")[2], { time: 3, value: 9 });
  });

  it("passes OHLC through for candles, hollow candles and bars", () => {
    assert.deepEqual(seriesData(bars, "candles"), bars);
    assert.deepEqual(seriesData(bars, "hollow"), bars);
    assert.deepEqual(seriesData(bars, "bars"), bars);
  });

  it("converts to Heikin Ashi", () => {
    assert.deepEqual(seriesData(bars, "heikin"), heikinAshi(bars));
  });
});
