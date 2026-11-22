"use client";

import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useMe } from "@/components/layout/AppShell";
import { LockIcon } from "@/components/ui/Icons";
import { Tip } from "@/components/ui/Tip";
import { api } from "@/lib/api";
import type { ChartTimeframe, Instrument, PatternFilter, SetupDetail } from "@/lib/types";

import type { Tool } from "./Chart";
import { CHART_STYLES, type ChartStyle, isChartStyle } from "./chartStyle";
import { LayoutIcon, StyleIcons, UiIcons } from "./icons";
import { Menu } from "./Menu";
import type { Layers } from "./Overlays";
import { Panel, type PanelConfig, type PanelHandle, type PanelState, TIMEFRAMES } from "./Panel";
import { SidePanel, type SideTab } from "./SidePanel";
import { TOOLS, ToolRail } from "./ToolRail";

export type Layout = "1" | "2h" | "2v" | "4";
const LAYOUTS: { value: Layout; label: string; key: string; panels: number }[] = [
  { value: "1", label: "1 chart", key: "Alt+1", panels: 1 },
  { value: "2h", label: "2 side by side", key: "Alt+2", panels: 2 },
  { value: "2v", label: "2 stacked", key: "Alt+3", panels: 2 },
  { value: "4", label: "4 charts", key: "Alt+4", panels: 4 },
];
const PRESETS = ["default", "scalping", "intraday", "swing"];
const LAYER_NAMES: { key: keyof Layers; label: string }[] = [
  { key: "structure", label: "Structure" },
  { key: "zones", label: "Zones" },
  { key: "liquidity", label: "Liquidity" },
  { key: "provisional", label: "Provisional swings" },
];
const DEFAULT_LAYERS: Layers = { structure: true, zones: true, liquidity: true, provisional: true };
const TOOL_KEYS: Record<string, Tool> = Object.fromEntries(
  TOOLS.map((t) => [t.key.toLowerCase(), t.tool]),
);

type Saved = {
  layout: Layout;
  panels: Omit<PanelConfig, "setupId">[];
  link: boolean;
  side: boolean;
};

function storageKey(userId: string) {
  return `tl:workspace:v1:${userId}`;
}

function readSaved(userId: string): Partial<Saved> {
  try {
    return JSON.parse(window.localStorage.getItem(storageKey(userId)) ?? "{}") as Partial<Saved>;
  } catch {
    return {};
  }
}

function useMedia(query: string): boolean {
  const [match, setMatch] = useState(false);
  useEffect(() => {
    const m = window.matchMedia(query);
    setMatch(m.matches);
    const on = () => setMatch(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [query]);
  return match;
}

type Props = {
  instrument: string;
  timeframe: ChartTimeframe;
  setupId: string | null;
  /** From the scanner page: scroll the first chart to this item (CR-006). */
  initialFocus?: { time: string; zoneId?: string } | null;
  /** Patterns chosen in the scanner before the chart opened (CR-006). */
  initialPatterns?: Pick<PatternFilter, "patterns" | "match"> | null;
  /** The scanner for the side panel; the workspace passes how to open a setup, the chosen
   *  patterns (the chart shows only those) and how to focus an analysis item. */
  renderScanner: (handlers: ScannerHandlers) => ReactNode;
};

export type FocusTarget = {
  instrument: string;
  timeframe: string;
  time: string;
  zoneId?: string;
  setupId?: string;
};
export type ScannerHandlers = {
  onOpen: (row: { instrument: string; timeframe: string; id: string }) => void;
  onPatternsChange: (f: Pick<PatternFilter, "patterns" | "match">) => void;
  onFocus: (target: FocusTarget) => void;
  initialPatterns: Pick<PatternFilter, "patterns" | "match"> | null;
};

// Chart workspace: 1, 2 or 4 charts with drawing tools, chart styles, a scanner and watchlist
// side panel, full screen and live prices. Analytics only: there are no order controls.
export function Workspace({
  instrument,
  timeframe,
  setupId,
  initialFocus,
  initialPatterns,
  renderScanner,
}: Props) {
  const me = useMe();
  const isPro = me.entitlements.mtf_detail === "full";
  const phone = useMedia("(max-width: 767px)");
  const docked = useMedia("(min-width: 1200px)");

  const first: PanelConfig = {
    instrument,
    timeframe,
    style: "candles",
    layers: DEFAULT_LAYERS,
    preset: "default",
    setupId,
  };
  const [layout, setLayout] = useState<Layout>("1");
  const [panels, setPanels] = useState<PanelConfig[]>([first]);
  const [active, setActive] = useState(0);
  const [link, setLink] = useState(false);
  const [sideOpen, setSideOpen] = useState<boolean>(true);
  const [sideTab, setSideTab] = useState<SideTab>(setupId ? "setup" : "setups");
  const [tool, setTool] = useState<Tool>("select");
  const [cancelNonce, setCancelNonce] = useState(0);
  const [patterns, setPatterns] = useState<Pick<PatternFilter, "patterns" | "match">>(
    initialPatterns ?? { patterns: [], match: "any" },
  );
  const [others, setOthers] = useState<PatternFilter["others"]>("fade");
  const [focus, setFocus] = useState<{ time: string; zoneId?: string; nonce: number } | null>(
    initialFocus ? { ...initialFocus, nonce: 1 } : null,
  );
  const [full, setFull] = useState<null | "panel" | "workspace">(null);
  const [sheet, setSheet] = useState(false);
  const [setup, setSetup] = useState<SetupDetail | null>(null);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [states, setStates] = useState<(PanelState | null)[]>([null, null, null, null]);
  const handles = useRef<(PanelHandle | null)[]>([null, null, null, null]);
  const root = useRef<HTMLDivElement | null>(null);
  const restored = useRef(false);

  // Restore the saved workspace once (layout, other charts, link, side panel); the address
  // decides the first chart.
  useEffect(() => {
    const s = readSaved(me.user.id);
    const saved = (s.panels ?? []).filter((p) => p && typeof p.instrument === "string");
    const lay = isPro && s.layout && LAYOUTS.some((l) => l.value === s.layout) ? s.layout : "1";
    const firstStyle = isChartStyle(saved[0]?.style) ? saved[0].style : "candles";
    setPanels([
      { ...first, style: firstStyle, layers: saved[0]?.layers ?? DEFAULT_LAYERS },
      ...[1, 2, 3].map((i) => ({
        ...first,
        ...(saved[i] ?? {}),
        style: isChartStyle(saved[i]?.style) ? (saved[i].style as ChartStyle) : firstStyle,
        layers: saved[i]?.layers ?? DEFAULT_LAYERS,
        setupId: null,
      })),
    ]);
    setLayout(lay);
    setLink(s.link === true);
    // Beside the charts (1,200 px and up) the side panel opens as saved, and always with a
    // setup to show; on smaller screens it covers the charts, so it waits for the button.
    const roomy = window.innerWidth >= 1200;
    setSideOpen(roomy && (Boolean(setupId) || s.side !== false));
    restored.current = true;
    // Run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!restored.current) return;
    const s: Saved = {
      layout,
      panels: panels.map((p) => ({ ...p, setupId: undefined })),
      link,
      side: sideOpen,
    };
    try {
      window.localStorage.setItem(storageKey(me.user.id), JSON.stringify(s));
    } catch {
      // Storage blocked: the workspace resets next visit.
    }
  }, [layout, panels, link, sideOpen, me.user.id]);

  useEffect(() => {
    void api<{ items: Instrument[] }>("/instruments").then((r) => setInstruments(r.items));
  }, []);

  const count = phone ? 1 : (LAYOUTS.find((l) => l.value === layout)?.panels ?? 1);
  const shown = phone ? [active] : Array.from({ length: count }, (_, i) => i);
  const activeIdx = shown.includes(active) ? active : 0;
  const cfg = panels[activeIdx] ?? panels[0];

  // The address follows the active chart, without reloading the page.
  useEffect(() => {
    if (!cfg) return;
    const url = `/chart/${cfg.instrument}/${cfg.timeframe}${cfg.setupId ? `?setup=${cfg.setupId}` : ""}`;
    if (window.location.pathname + window.location.search !== url)
      window.history.replaceState(window.history.state, "", url);
  }, [cfg]);

  const update = useCallback(
    (index: number, next: Partial<PanelConfig>) => {
      setPanels((cur) =>
        cur.map((p, i) => {
          if (i === index) return { ...p, ...next };
          if (link && next.instrument && next.instrument !== p.instrument)
            return { ...p, instrument: next.instrument, setupId: null };
          return p;
        }),
      );
    },
    [link],
  );

  const pick = useCallback(
    (inst: string, tf: string | null, id: string | null) => {
      const next: Partial<PanelConfig> = { instrument: inst, setupId: id };
      if (tf && (TIMEFRAMES as string[]).includes(tf)) next.timeframe = tf as ChartTimeframe;
      update(activeIdx, next);
      if (id) setSideTab("setup");
      if (!docked) setSideOpen(false);
    },
    [activeIdx, update, docked],
  );

  const openFromScanner = useCallback(
    (row: { instrument: string; timeframe: string; id: string }) =>
      pick(row.instrument, row.timeframe, row.id),
    [pick],
  );
  const onPatternsChange = useCallback(
    (f: Pick<PatternFilter, "patterns" | "match">) =>
      setPatterns((cur) =>
        cur.match === f.match && cur.patterns.join() === f.patterns.join() ? cur : f,
      ),
    [],
  );
  const onFocus = useCallback(
    (t: FocusTarget) => {
      const next: Partial<PanelConfig> = { instrument: t.instrument };
      if ((TIMEFRAMES as string[]).includes(t.timeframe))
        next.timeframe = t.timeframe as ChartTimeframe;
      if (t.setupId) next.setupId = t.setupId;
      update(activeIdx, next);
      setFocus((f) => ({ time: t.time, zoneId: t.zoneId, nonce: (f?.nonce ?? 0) + 1 }));
    },
    [activeIdx, update],
  );
  const scanner = useMemo(
    () =>
      renderScanner({
        onOpen: openFromScanner,
        onPatternsChange,
        onFocus,
        initialPatterns: initialPatterns ?? null,
      }),
    // initialPatterns only seeds the scanner once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [renderScanner, openFromScanner, onPatternsChange, onFocus],
  );
  const patternFilter = useMemo<PatternFilter | null>(
    () => (patterns.patterns.length ? { ...patterns, others } : null),
    [patterns, others],
  );

  const onSetup = useCallback((s: SetupDetail | null) => setSetup(s), []);
  const stateSetters = useMemo(
    () =>
      [0, 1, 2, 3].map(
        (i) => (s: PanelState) =>
          setStates((cur) => {
            const next = [...cur];
            next[i] = s;
            return next;
          }),
      ),
    [],
  );
  const handleSetters = useMemo(
    () => [0, 1, 2, 3].map((i) => (h: PanelHandle | null) => (handles.current[i] = h)),
    [],
  );
  const h = () => handles.current[activeIdx];

  const chooseLayout = useCallback(
    (l: Layout) => {
      if (!isPro && l !== "1") return;
      setLayout(l);
      const n = LAYOUTS.find((x) => x.value === l)?.panels ?? 1;
      if (active >= n) setActive(0);
    },
    [isPro, active],
  );

  // ---------------------------------------------------------------- full screen
  const toggleFull = useCallback(
    async (target: "panel" | "workspace") => {
      if (full) {
        if (document.fullscreenElement) await document.exitFullscreen().catch(() => undefined);
        setFull(null);
        return;
      }
      const el =
        target === "panel"
          ? root.current?.querySelector<HTMLElement>("[data-active=true]")
          : root.current;
      setFull(target);
      if (el?.requestFullscreen) await el.requestFullscreen().catch(() => undefined);
    },
    [full],
  );

  useEffect(() => {
    const on = () => {
      if (!document.fullscreenElement) setFull(null);
    };
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);

  // ---------------------------------------------------------------- keyboard
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.closest("input, select, textarea, [contenteditable=true]") || t.isContentEditable)
      )
        return;
      if (t?.closest("[role=menu], [role=alertdialog]")) return;
      const k = e.key.toLowerCase();
      const mod = e.ctrlKey || e.metaKey;
      if (e.key === "Escape") {
        if (tool !== "select" || sheet) {
          setTool("select");
          setSheet(false);
          setCancelNonce((n) => n + 1);
        } else if (full) {
          void toggleFull("panel");
        } else setCancelNonce((n) => n + 1);
        return;
      }
      if (mod && k === "z") {
        e.preventDefault();
        if (e.shiftKey) h()?.redo();
        else h()?.undo();
        return;
      }
      if (mod && k === "y") {
        e.preventDefault();
        h()?.redo();
        return;
      }
      if (mod) return;
      if (e.altKey && ["1", "2", "3", "4"].includes(e.key)) {
        e.preventDefault();
        chooseLayout(LAYOUTS[Number(e.key) - 1].value);
        return;
      }
      if (e.altKey) return;
      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        h()?.deleteSelected();
        return;
      }
      if (e.shiftKey && k === "l") return h()?.toggleLock();
      if (e.shiftKey && k === "h") return h()?.toggleHidden();
      if (e.shiftKey && k === "f") return void toggleFull("panel");
      if (e.key === "]") return setSideOpen((o) => !o);
      if (e.key.startsWith("Arrow") && states[activeIdx]?.selected) {
        e.preventDefault();
        const step = e.shiftKey ? 10 : 1;
        if (e.key === "ArrowLeft") h()?.nudge(-step, 0);
        if (e.key === "ArrowRight") h()?.nudge(step, 0);
        if (e.key === "ArrowUp") h()?.nudge(0, step);
        if (e.key === "ArrowDown") h()?.nudge(0, -step);
        return;
      }
      if (!e.shiftKey && TOOL_KEYS[k]) setTool(TOOL_KEYS[k]);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // h reads the ref at call time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool, sheet, full, toggleFull, chooseLayout, states, activeIdx]);

  const toolDone = useCallback(() => setTool("select"), []);
  const state = states[activeIdx];
  const styleLabel = CHART_STYLES.find((s) => s.value === cfg.style)?.label ?? "Candles";
  const overlay = !docked;
  const showSide = sideOpen;

  const rail = (variant: "rail" | "sheet") => (
    <ToolRail
      variant={variant}
      tool={tool}
      state={state}
      onTool={(t) => {
        setTool(t);
        if (variant === "sheet") setSheet(false);
      }}
      onUndo={() => h()?.undo()}
      onRedo={() => h()?.redo()}
      onDeleteSelected={() => h()?.deleteSelected()}
      onDeleteAll={() => h()?.deleteAll()}
      onToggleLock={() => h()?.toggleLock()}
      onToggleHidden={() => h()?.toggleHidden()}
    />
  );

  return (
    <div
      className="ws"
      ref={root}
      data-testid="workspace"
      data-layout={phone ? "1" : layout}
      data-fullscreen={full ?? undefined}
      data-side={showSide ? (overlay ? "overlay" : "docked") : "closed"}
    >
      <div className="ws-top" role="toolbar" aria-label="Chart workspace">
        {phone && (
          <button
            type="button"
            className="ws-btn"
            aria-expanded={sheet}
            onClick={() => setSheet((s) => !s)}
          >
            {UiIcons.tools}
            <span>Tools</span>
          </button>
        )}
        <Menu
          label={`Chart style: ${styleLabel}`}
          button={
            <>
              {StyleIcons[cfg.style]}
              <span className="ws-btn__text">{styleLabel}</span>
              <span aria-hidden="true">▾</span>
            </>
          }
          items={CHART_STYLES.map((s) => ({
            key: s.value,
            label: s.label,
            icon: StyleIcons[s.value],
            checked: cfg.style === s.value,
            onSelect: () => update(activeIdx, { style: s.value }),
          }))}
          footer={
            cfg.style === "heikin"
              ? "Heikin Ashi candles are smoothed, not real prices. Setup scores always use real candles."
              : undefined
          }
        />
        {!phone && (
          <Menu
            label={`Layout: ${LAYOUTS.find((l) => l.value === layout)?.label}`}
            button={
              <>
                <LayoutIcon layout={layout} />
                <span className="ws-btn__text">Layout</span>
                <span aria-hidden="true">▾</span>
              </>
            }
            items={[
              ...LAYOUTS.map((l) => ({
                key: l.value,
                label: l.label,
                icon: <LayoutIcon layout={l.value} />,
                hint:
                  !isPro && l.value !== "1" ? (
                    <span className="lock-badge">
                      <LockIcon size={10} /> Pro
                    </span>
                  ) : (
                    <kbd>{l.key}</kbd>
                  ),
                checked: layout === l.value,
                disabled: !isPro && l.value !== "1",
                onSelect: () => chooseLayout(l.value),
              })),
              {
                key: "full-panel",
                label: "Full screen: active chart",
                icon: UiIcons.full,
                hint: <kbd>Shift+F</kbd>,
                checked: full === "panel",
                onSelect: () => void toggleFull("panel"),
              },
              {
                key: "full-ws",
                label: "Full screen: whole workspace",
                icon: UiIcons.full,
                checked: full === "workspace",
                onSelect: () => void toggleFull("workspace"),
              },
            ]}
            footer={
              isPro
                ? "Opens with 1 chart. Your choice is remembered on this device."
                : "More charts side by side are part of Pro."
            }
          />
        )}
        {!phone && count > 1 && (
          <button
            type="button"
            className="ws-btn"
            aria-pressed={link}
            title="Link symbol: changing the instrument updates every chart"
            onClick={() => setLink((l) => !l)}
          >
            {UiIcons.link}
            <span className="ws-btn__text">Link symbol</span>
          </button>
        )}
        <span className="ws-sep" aria-hidden="true" />
        <Menu
          label="Layers"
          stayOpen
          button={
            <>
              {UiIcons.layers}
              <span className="ws-btn__text">Layers</span>
              <span aria-hidden="true">▾</span>
            </>
          }
          items={[
            ...LAYER_NAMES.map((l) => ({
              key: l.key,
              kind: "check" as const,
              label: l.label,
              checked: cfg.layers[l.key],
              onSelect: () =>
                update(activeIdx, { layers: { ...cfg.layers, [l.key]: !cfg.layers[l.key] } }),
            })),
            ...(["fade", "hide"] as const).map((o) => ({
              key: `others-${o}`,
              label: o === "fade" ? "Unchosen patterns: faded" : "Unchosen patterns: hidden",
              checked: others === o,
              onSelect: () => setOthers(o),
            })),
          ]}
          footer={
            <>
              Provisional swings <Tip anchor="provisional" label="provisional swings" />
            </>
          }
        />
        <label className="ws-preset">
          <span className="ws-btn__text">Preset</span>
          <select
            name="preset"
            value={cfg.preset}
            onChange={(e) => update(activeIdx, { preset: e.target.value })}
          >
            {PRESETS.map((p) => (
              <option key={p} value={p}>
                {p.charAt(0).toUpperCase() + p.slice(1)}
              </option>
            ))}
          </select>
        </label>
        <span className="ws-grow" />
        <button
          type="button"
          className="ws-btn"
          aria-pressed={full !== null}
          aria-label={full ? "Exit full screen (Esc)" : "Full screen (Shift+F)"}
          title={full ? "Exit full screen (Esc)" : "Full screen (Shift+F)"}
          data-testid="fullscreen-button"
          onClick={() => void toggleFull("panel")}
        >
          {full ? UiIcons.exitFull : UiIcons.full}
        </button>
        <button
          type="button"
          className="ws-btn"
          aria-pressed={sideOpen}
          aria-label={sideOpen ? "Hide side panel (])" : "Show setups and watchlist (])"}
          title={sideOpen ? "Hide side panel (])" : "Show setups and watchlist (])"}
          onClick={() => setSideOpen((o) => !o)}
        >
          {UiIcons.side}
          <span className="ws-btn__text">Setups</span>
        </button>
      </div>

      <div className="ws-body">
        {!phone && rail("rail")}
        <div className={`ws-panels ws-panels--${phone ? "1" : layout}`}>
          {shown.map((i) => (
            <Panel
              key={i}
              index={i}
              config={panels[i] ?? panels[0]}
              active={i === activeIdx}
              compact={count > 2}
              instruments={instruments}
              tool={i === activeIdx ? tool : "select"}
              cancelNonce={cancelNonce}
              onActivate={() => setActive(i)}
              onChange={(next) => update(i, next)}
              onToolDone={toolDone}
              onSetup={onSetup}
              onState={stateSetters[i]}
              handleRef={handleSetters[i]}
              patternFilter={patternFilter}
              focus={i === activeIdx ? focus : null}
            />
          ))}
        </div>
        {showSide && (
          <SidePanel
            tab={sideTab}
            onTab={setSideTab}
            onClose={() => setSideOpen(false)}
            scanner={scanner}
            setup={setup}
            timeZone={me.user.timezone}
            onPick={pick}
            overlay={overlay}
          />
        )}
      </div>

      {phone && sheet && (
        <div className="ws-sheet" role="dialog" aria-label="Drawing tools">
          <span className="ws-sheet__grab" aria-hidden="true" />
          {rail("sheet")}
        </div>
      )}
      <p className="sr-only" aria-live="polite">
        {tool !== "select"
          ? `${TOOLS.find((t) => t.tool === tool)?.label} selected. Click on the chart to place it. Esc cancels.`
          : ""}
      </p>
    </div>
  );
}
