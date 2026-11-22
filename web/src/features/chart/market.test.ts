// Unit tests for the market clock: trading day, countdown, weekend (npm run test:unit).
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  dayChange,
  formatCountdown,
  isMarketClosed,
  nextCloseMs,
  tradingDayStart,
} from "./market.ts";

const utc = (s: string) => Date.parse(s);

describe("tradingDayStart", () => {
  it("starts at 17:00 New York (22:00 UTC in winter)", () => {
    // Tue 18 Nov 2026 10:00 UTC -> day began Mon 17 Nov 22:00 UTC.
    assert.equal(tradingDayStart(utc("2026-11-18T10:00:00Z")), utc("2026-11-17T22:00:00Z"));
    // Just after the roll.
    assert.equal(tradingDayStart(utc("2026-11-18T22:05:00Z")), utc("2026-11-18T22:00:00Z"));
  });

  it("follows daylight saving (21:00 UTC in summer)", () => {
    assert.equal(tradingDayStart(utc("2026-07-15T12:00:00Z")), utc("2026-07-14T21:00:00Z"));
  });
});

describe("isMarketClosed", () => {
  it("is closed from Friday 17:00 to Sunday 17:00 New York", () => {
    assert.equal(isMarketClosed(utc("2026-11-20T21:59:00Z")), false); // Fri 16:59 NY
    assert.equal(isMarketClosed(utc("2026-11-20T22:01:00Z")), true); // Fri 17:01 NY
    assert.equal(isMarketClosed(utc("2026-11-21T12:00:00Z")), true); // Sat
    assert.equal(isMarketClosed(utc("2026-11-22T21:59:00Z")), true); // Sun 16:59 NY
    assert.equal(isMarketClosed(utc("2026-11-22T22:01:00Z")), false); // Sun 17:01 NY
  });
});

describe("nextCloseMs", () => {
  it("closes one candle after the forming candle opens", () => {
    // Last complete H1 candle opened 10:00; forming opened 11:00; closes 12:00.
    const last = utc("2026-11-18T10:00:00Z") / 1000;
    assert.equal(nextCloseMs(last, 3600, utc("2026-11-18T11:20:00Z")), utc("2026-11-18T12:00:00Z"));
  });

  it("skips ahead when candles are missing", () => {
    const last = utc("2026-11-18T10:00:00Z") / 1000;
    assert.equal(nextCloseMs(last, 3600, utc("2026-11-18T14:10:00Z")), utc("2026-11-18T15:00:00Z"));
  });
});

describe("formatCountdown", () => {
  it("shows minutes and seconds under an hour", () => {
    assert.equal(formatCountdown(12 * 60_000 + 41_000), "12:41");
    assert.equal(formatCountdown(5_000), "00:05");
  });
  it("shows hours and minutes under a day", () => {
    assert.equal(formatCountdown(2 * 3_600_000 + 5 * 60_000), "2h 05m");
  });
  it("shows days and hours beyond that", () => {
    assert.equal(formatCountdown(26 * 3_600_000), "1d 2h");
  });
  it("never goes negative", () => {
    assert.equal(formatCountdown(-500), "00:00");
  });
});

describe("dayChange", () => {
  const candles = [
    { t: "2026-11-17T21:00:00Z", o: 108000, c: 108100 },
    { t: "2026-11-17T22:00:00Z", o: 108100, c: 108200 },
    { t: "2026-11-17T23:00:00Z", o: 108200, c: 108300 },
  ];
  it("compares the last price with the open of the trading day", () => {
    const ch = dayChange(candles, 108400, utc("2026-11-18T01:00:00Z"));
    assert.ok(ch);
    assert.equal(ch.units, 300);
    assert.ok(Math.abs(ch.percent - 0.2775) < 0.001);
  });
  it("is null when there is no candle in the day yet", () => {
    assert.equal(dayChange(candles.slice(0, 1), 108400, utc("2026-11-18T01:00:00Z")), null);
    assert.equal(dayChange(candles, null, utc("2026-11-18T01:00:00Z")), null);
  });
});
