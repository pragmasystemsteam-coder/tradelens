"use client";

import { type ReactNode, useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { formatPrice } from "@/lib/price";
import type { SetupDetail, Watchlist, WatchlistItem } from "@/lib/types";

import { UiIcons } from "./icons";
import { SetupPanel } from "./SetupPanel";

export type SideTab = "setups" | "watchlist" | "setup";

type Props = {
  tab: SideTab;
  onTab: (t: SideTab) => void;
  onClose: () => void;
  scanner: ReactNode;
  setup: SetupDetail | null;
  timeZone: string;
  onPick: (instrument: string, timeframe: string | null, setupId: string | null) => void;
  overlay: boolean;
};

const TABS: { id: SideTab; label: string }[] = [
  { id: "setups", label: "Setups" },
  { id: "watchlist", label: "Watchlist" },
  { id: "setup", label: "Setup" },
];

function WatchlistTab({ onPick }: { onPick: Props["onPick"] }) {
  const [lists, setLists] = useState<Watchlist[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [items, setItems] = useState<WatchlistItem[] | null>(null);

  useEffect(() => {
    void api<{ items: Watchlist[] }>("/watchlists").then((r) => {
      setLists(r.items);
      setSelected(r.items[0]?.id ?? null);
    });
  }, []);

  const load = useCallback(async () => {
    if (!selected) return setItems(null);
    const d = await api<{ items: WatchlistItem[] }>(`/watchlists/${selected}`);
    setItems(d.items);
  }, [selected]);

  useEffect(() => {
    void load();
  }, [load]);

  if (lists.length === 0)
    return (
      <div className="empty">
        <strong>No watchlists yet</strong>
        <span>Create one on the Watchlists page, then pick pairs here.</span>
      </div>
    );
  return (
    <div className="side-watch">
      {lists.length > 1 && (
        <label className="side-watch__pick">
          <span className="sr-only">Watchlist</span>
          <select value={selected ?? ""} onChange={(e) => setSelected(e.target.value)}>
            {lists.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <ul className="side-watch__list">
        {items?.length === 0 && <li className="hint">This watchlist is empty.</li>}
        {items?.map((it) => (
          <li key={it.instrument}>
            <button
              type="button"
              className="side-watch__row"
              data-testid="side-watch-row"
              onClick={() =>
                onPick(it.instrument, it.best_setup?.timeframe ?? null, it.best_setup?.id ?? null)
              }
            >
              <strong>{it.display_name}</strong>
              <span>{formatPrice(it.last_price, it.price_scale)}</span>
              {it.best_setup ? (
                <span className={`score-link score-link--${it.best_setup.direction}`}>
                  <span className="score">{it.best_setup.combined}</span>
                  {it.best_setup.direction === "bull" ? "▲" : "▼"}{" "}
                  {it.best_setup.timeframe.toUpperCase()}
                </span>
              ) : (
                <span className="muted">No setup</span>
              )}
              {it.data_status !== "ok" && <span className="badge badge--delayed">Delayed</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Setups, watchlist and the open setup's details beside the charts. Every tab stays mounted
// so the scanner keeps its filters while you switch.
export function SidePanel(props: Props) {
  const { tab, onTab } = props;
  return (
    <aside
      className={`ws-side${props.overlay ? " ws-side--overlay" : ""}`}
      aria-label="Setups and watchlist"
      data-testid="side-panel"
    >
      <div className="ws-side__tabs" role="tablist" aria-label="Side panel">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`side-tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`side-panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            className={tab === t.id ? "tab tab--on" : "tab"}
            onClick={() => onTab(t.id)}
            onKeyDown={(e) => {
              if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
              const i = TABS.findIndex((x) => x.id === tab);
              const next =
                TABS[(i + (e.key === "ArrowRight" ? 1 : -1) + TABS.length) % TABS.length];
              onTab(next.id);
              document.getElementById(`side-tab-${next.id}`)?.focus();
            }}
          >
            {t.label}
          </button>
        ))}
        <button
          type="button"
          className="ws-btn ws-side__close"
          aria-label="Close side panel (])"
          title="Close side panel (])"
          onClick={props.onClose}
        >
          {UiIcons.close}
        </button>
      </div>
      <div
        className="ws-side__body"
        role="tabpanel"
        id="side-panel-setups"
        aria-labelledby="side-tab-setups"
        hidden={tab !== "setups"}
      >
        {props.scanner}
      </div>
      <div
        className="ws-side__body"
        role="tabpanel"
        id="side-panel-watchlist"
        aria-labelledby="side-tab-watchlist"
        hidden={tab !== "watchlist"}
      >
        {tab === "watchlist" && <WatchlistTab onPick={props.onPick} />}
      </div>
      <div
        className="ws-side__body"
        role="tabpanel"
        id="side-panel-setup"
        aria-labelledby="side-tab-setup"
        hidden={tab !== "setup"}
      >
        {props.setup ? (
          <SetupPanel setup={props.setup} timeZone={props.timeZone} />
        ) : (
          <div className="empty">
            <strong>No setup open</strong>
            <span>Pick a setup in the Setups tab to see its score, reasons and levels here.</span>
          </div>
        )}
      </div>
    </aside>
  );
}
