"use client";

import { useState } from "react";

import type { Tool } from "./Chart";
import { ToolIcons } from "./icons";
import type { PanelState } from "./Panel";

export const TOOLS: { tool: Tool; label: string; key: string }[] = [
  { tool: "select", label: "Select and move", key: "V" },
  { tool: "trend", label: "Trend line", key: "T" },
  { tool: "hline", label: "Horizontal line", key: "H" },
  { tool: "ray", label: "Ray", key: "R" },
  { tool: "rect", label: "Rectangle (zone)", key: "Z" },
  { tool: "fib", label: "Fibonacci retracement", key: "F" },
  { tool: "text", label: "Text note", key: "N" },
  { tool: "measure", label: "Measure", key: "M" },
];

type Props = {
  tool: Tool;
  state: PanelState | null;
  onTool: (t: Tool) => void;
  onUndo: () => void;
  onRedo: () => void;
  onDeleteSelected: () => void;
  onDeleteAll: () => void;
  onToggleLock: () => void;
  onToggleHidden: () => void;
  variant: "rail" | "sheet";
};

// Drawing tools for the active chart: a rail on tablet and desktop, a grid in the phone sheet.
export function ToolRail(props: Props) {
  const { tool, state, variant } = props;
  const [confirm, setConfirm] = useState(false);
  const count = state?.count ?? 0;
  return (
    <div
      className={variant === "rail" ? "tool-rail" : "tool-sheet"}
      role="toolbar"
      aria-label="Drawing tools"
      aria-orientation={variant === "rail" ? "vertical" : "horizontal"}
    >
      {TOOLS.map((t) => (
        <button
          key={t.tool}
          type="button"
          className="tool-btn"
          aria-pressed={tool === t.tool}
          aria-label={`${t.label} (${t.key})`}
          title={`${t.label} (${t.key})`}
          data-tool={t.tool}
          onClick={() => props.onTool(t.tool)}
        >
          {ToolIcons[t.tool]}
          {variant === "sheet" && <span>{t.label.split(" (")[0]}</span>}
        </button>
      ))}
      <span className="tool-sep" aria-hidden="true" />
      <button
        type="button"
        className="tool-btn"
        aria-label="Undo (Ctrl+Z)"
        title="Undo (Ctrl+Z)"
        disabled={!state?.canUndo}
        onClick={props.onUndo}
      >
        {ToolIcons.undo}
        {variant === "sheet" && <span>Undo</span>}
      </button>
      <button
        type="button"
        className="tool-btn"
        aria-label="Redo (Ctrl+Shift+Z)"
        title="Redo (Ctrl+Shift+Z)"
        disabled={!state?.canRedo}
        onClick={props.onRedo}
      >
        {ToolIcons.redo}
        {variant === "sheet" && <span>Redo</span>}
      </button>
      <button
        type="button"
        className="tool-btn"
        aria-label="Delete selected drawing (Delete)"
        title="Delete selected drawing (Delete)"
        disabled={!state?.selected || state.locked}
        onClick={props.onDeleteSelected}
      >
        {ToolIcons.erase}
        {variant === "sheet" && <span>Delete</span>}
      </button>
      <button
        type="button"
        className="tool-btn"
        aria-pressed={state?.locked ?? false}
        aria-label="Lock drawings (Shift+L)"
        title="Lock drawings (Shift+L)"
        onClick={props.onToggleLock}
      >
        {ToolIcons.lock}
        {variant === "sheet" && <span>Lock</span>}
      </button>
      <button
        type="button"
        className="tool-btn"
        aria-pressed={state?.hidden ?? false}
        aria-label="Hide drawings (Shift+H)"
        title="Hide drawings (Shift+H)"
        onClick={props.onToggleHidden}
      >
        {state?.hidden ? ToolIcons.eyeOff : ToolIcons.eye}
        {variant === "sheet" && <span>Hide</span>}
      </button>
      <div className="tool-confirm-root">
        <button
          type="button"
          className="tool-btn"
          aria-label="Delete all drawings"
          title="Delete all drawings"
          aria-expanded={confirm}
          disabled={count === 0 || state?.locked}
          onClick={() => setConfirm((c) => !c)}
        >
          {ToolIcons.trash}
          {variant === "sheet" && <span>Delete all</span>}
        </button>
        {confirm && (
          <div className="tool-confirm" role="alertdialog" aria-label="Delete all drawings">
            <p>
              Delete {count} {count === 1 ? "drawing" : "drawings"} on {state?.label}? You can undo
              this.
            </p>
            <div className="tool-confirm__actions">
              <button
                type="button"
                className="button button--secondary"
                onClick={() => setConfirm(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="button"
                autoFocus
                onClick={() => {
                  props.onDeleteAll();
                  setConfirm(false);
                }}
              >
                Delete all
              </button>
            </div>
          </div>
        )}
      </div>
      {variant === "sheet" && (
        <p className="hint tool-sheet__hint">
          Drawings are saved in this browser. Tap a start point, then an end point.
        </p>
      )}
    </div>
  );
}
