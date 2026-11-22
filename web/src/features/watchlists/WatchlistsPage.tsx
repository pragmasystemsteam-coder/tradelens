"use client";

import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { useMe } from "@/components/layout/AppShell";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { WarnIcon } from "@/components/ui/Icons";
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
  const [loaded, setLoaded] = useState(false);

  const loadLists = useCallback(async () => {
    const body = await api<{ items: Watchlist[]; limits: { max_watchlists: number | null } }>(
      "/watchlists",
    );
    setLists(body.items);
    setLimits(body.limits);
    setSelected((cur) => cur ?? body.items[0]?.id ?? null);
    setLoaded(true);
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

  const max = limits?.max_watchlists ?? null;
  const atLimit = max !== null && lists.length >= max;

  return (
    <div className="watchlists-page">
      <aside className="watchlist-side" aria-label="Your watchlists">
        <h1>Watchlists</h1>
        <ul className="watchlist-tabs">
          {lists.map((w) => (
            <li key={w.id}>
              <button
                type="button"
                className="watchlist-tab"
                aria-current={w.id === selected ? "true" : undefined}
                onClick={() => setSelected(w.id)}
              >
                {w.name}
              </button>
            </li>
          ))}
        </ul>
        <form className="inline-form" onSubmit={create}>
          <input
            aria-label="New watchlist name"
            value={name}
            maxLength={60}
            onChange={(e) => setName(e.target.value)}
            placeholder="New watchlist"
            required
          />
          <button type="submit" className="button button--secondary">
            Create
          </button>
        </form>
        {limits && (
          <span className="hint">
            {max === null
              ? `${lists.length} watchlists`
              : `${lists.length} of ${max} ${max === 1 ? "watchlist" : "watchlists"} used`}
            {atLimit ? ". You are at your plan's limit." : ""}
          </span>
        )}
      </aside>
      <section className="watchlist-main" aria-label={detail?.name ?? "Watchlist"}>
        {error?.needsUpgrade && <ProLock label="raises your watchlist and instrument limits" />}
        {error && !error.needsUpgrade && (
          <p className="banner banner--error error" role="alert" data-testid="watchlist-error">
            <WarnIcon />
            <span>
              {error.code === "plan_limit"
                ? "You have reached the limit of your plan."
                : error.message}
            </span>
          </p>
        )}
        {loaded && lists.length === 0 && (
          <div className="empty" role="status">
            <strong>You have no watchlists yet</strong>
            <span>Name one on the left, then add the pairs you trade.</span>
          </div>
        )}
        {detail && (
          <>
            <div className="watchlist-main__head">
              <h2>{detail.name}</h2>
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
            </div>
            {detail.items.length === 0 ? (
              <div className="empty" role="status">
                <strong>This watchlist is empty</strong>
                <span>Add an instrument to see its last price and best setup here.</span>
              </div>
            ) : (
              <div className="table-wrap">
                <table className="watchlist-table" data-testid="watchlist-table">
                  <thead>
                    <tr>
                      <th scope="col">Instrument</th>
                      <th scope="col">Last</th>
                      <th scope="col">Best setup</th>
                      <th scope="col">Data</th>
                      <th scope="col">
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.items.map((it) => (
                      <tr key={it.instrument}>
                        <td>
                          <strong>{it.display_name}</strong>
                        </td>
                        <td>{formatPrice(it.last_price, it.price_scale)}</td>
                        <td>
                          {it.best_setup ? (
                            <Link
                              className={`score-link score-link--${it.best_setup.direction}`}
                              href={`/chart/${it.instrument}/${it.best_setup.timeframe}?setup=${it.best_setup.id}`}
                            >
                              <span className="score">{it.best_setup.combined}</span>
                              <span>
                                {it.best_setup.direction === "bull" ? "▲ Bullish" : "▼ Bearish"}{" "}
                                {it.best_setup.timeframe.toUpperCase()}
                              </span>
                            </Link>
                          ) : (
                            <span className="muted">No setup</span>
                          )}
                        </td>
                        <td>
                          {it.data_status === "ok" ? (
                            <span className="data-ok">OK</span>
                          ) : (
                            <span className="badge badge--delayed">Data delayed</span>
                          )}
                        </td>
                        <td>
                          <button
                            type="button"
                            className="link-button"
                            aria-label={`Remove ${it.display_name}`}
                            onClick={() => void remove(it.instrument)}
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <Disclaimer />
          </>
        )}
      </section>
    </div>
  );
}
