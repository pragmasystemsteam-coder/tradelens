"use client";

import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { useMe } from "@/components/layout/AppShell";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { ProLock } from "@/components/ui/ProLock";
import { api, ApiError } from "@/lib/api";
import { formatPrice } from "@/lib/price";
import type { Instrument, Watchlist, WatchlistItem } from "@/lib/types";

type Detail = { id: string; name: string; items: WatchlistItem[] };

// Watchlists with last price, best setup and data status (FR-WATCH-01, FR-WATCH-02).
export function WatchlistsPage() {
  useMe();
  const [lists, setLists] = useState<Watchlist[]>([]);
  const [limits, setLimits] = useState<{ max_watchlists: number | null } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<ApiError | null>(null);

  const loadLists = useCallback(async () => {
    const body = await api<{ items: Watchlist[]; limits: { max_watchlists: number | null } }>(
      "/watchlists",
    );
    setLists(body.items);
    setLimits(body.limits);
    setSelected((cur) => cur ?? body.items[0]?.id ?? null);
  }, []);

  const loadDetail = useCallback(async () => {
    if (selected) setDetail(await api<Detail>(`/watchlists/${selected}`));
    else setDetail(null);
  }, [selected]);

  useEffect(() => {
    void loadLists();
    void api<{ items: Instrument[] }>("/instruments").then((r) => setInstruments(r.items));
  }, [loadLists]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  async function guard(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
    } catch (err) {
      if (err instanceof ApiError) setError(err);
      else throw err;
    }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    await guard(async () => {
      const made = await api<Watchlist>("/watchlists", { method: "POST", body: { name } });
      setName("");
      setSelected(made.id);
      await loadLists();
    });
  }

  async function add(code: string) {
    if (!selected || !code) return;
    await guard(async () => {
      await api(`/watchlists/${selected}/items/${code}`, { method: "PUT" });
      await loadDetail();
    });
  }

  async function remove(code: string) {
    if (!selected) return;
    await guard(async () => {
      await api(`/watchlists/${selected}/items/${code}`, { method: "DELETE" });
      await loadDetail();
    });
  }

  return (
    <div className="watchlists-page">
      <h1>Watchlists</h1>
      <div className="watchlist-tabs">
        {lists.map((w) => (
          <button
            key={w.id}
            type="button"
            className={w.id === selected ? "chip chip--on" : "chip"}
            onClick={() => setSelected(w.id)}
          >
            {w.name}
          </button>
        ))}
      </div>
      <form className="inline-form" onSubmit={create}>
        <input
          aria-label="New watchlist name"
          value={name}
          maxLength={60}
          onChange={(e) => setName(e.target.value)}
          placeholder="New watchlist"
          required
        />
        <button type="submit" className="button">
          Create
        </button>
        {limits && (
          <span className="hint">Up to {limits.max_watchlists ?? "unlimited"} watchlists</span>
        )}
      </form>
      {error?.needsUpgrade && <ProLock label="raises your watchlist and instrument limits" />}
      {error && !error.needsUpgrade && (
        <p className="error" role="alert" data-testid="watchlist-error">
          {error.code === "plan_limit" ? "You have reached the limit of your plan." : error.message}
        </p>
      )}
      {detail && (
        <section aria-label={detail.name}>
          <label>
            Add instrument
            <select value="" onChange={(e) => void add(e.target.value)}>
              <option value="">Choose…</option>
              {instruments
                .filter((i) => !detail.items.some((it) => it.instrument === i.code))
                .map((i) => (
                  <option key={i.code} value={i.code}>
                    {i.display_name}
                    {i.available ? "" : " (Pro)"}
                  </option>
                ))}
            </select>
          </label>
          <table className="watchlist-table" data-testid="watchlist-table">
            <thead>
              <tr>
                <th>Instrument</th>
                <th>Last</th>
                <th>Best setup</th>
                <th>Data</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {detail.items.map((it) => (
                <tr key={it.instrument}>
                  <td>{it.display_name}</td>
                  <td>{formatPrice(it.last_price, it.price_scale)}</td>
                  <td>
                    {it.best_setup ? (
                      <Link
                        href={`/chart/${it.instrument}/${it.best_setup.timeframe}?setup=${it.best_setup.id}`}
                      >
                        {it.best_setup.direction === "bull" ? "Bullish" : "Bearish"}{" "}
                        {it.best_setup.timeframe.toUpperCase()} · {it.best_setup.combined}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>
                    {it.data_status === "ok" ? (
                      "OK"
                    ) : (
                      <span className="badge badge--delayed">Data delayed</span>
                    )}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => void remove(it.instrument)}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Disclaimer />
        </section>
      )}
    </div>
  );
}
