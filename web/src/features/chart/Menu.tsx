"use client";

import { type ReactNode, useEffect, useId, useRef, useState } from "react";

export type MenuItem = {
  key: string;
  label: ReactNode;
  icon?: ReactNode;
  hint?: ReactNode;
  checked?: boolean;
  disabled?: boolean;
  /** "radio" (pick one) or "check" (toggle); default radio. */
  kind?: "radio" | "check";
  onSelect: () => void;
};

type Props = {
  label: string;
  button: ReactNode;
  items: MenuItem[];
  footer?: ReactNode;
  className?: string;
  /** Keep the menu open after choosing (checkbox menus). */
  stayOpen?: boolean;
};

// A small accessible dropdown: the button opens a menu; arrow keys move, Enter or Space
// chooses, Esc or a click outside closes and returns focus to the button.
export function Menu({ label, button, items, footer, className, stayOpen }: Props) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const root = useRef<HTMLDivElement | null>(null);
  const btn = useRef<HTMLButtonElement | null>(null);
  const list = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const first = list.current?.querySelector<HTMLElement>(
      "[role^=menuitem]:not([aria-disabled=true])",
    );
    first?.focus();
    const onDown = (e: PointerEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  function onKey(e: React.KeyboardEvent) {
    const els = Array.from(list.current?.querySelectorAll<HTMLElement>("[role^=menuitem]") ?? []);
    const i = els.indexOf(document.activeElement as HTMLElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const n = els.length;
      const next = els[(i + (e.key === "ArrowDown" ? 1 : -1) + n) % n];
      next?.focus();
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      els[e.key === "Home" ? 0 : els.length - 1]?.focus();
    } else if (e.key === "Escape" || e.key === "Tab") {
      e.stopPropagation();
      setOpen(false);
      if (e.key === "Escape") btn.current?.focus();
    }
  }

  return (
    <div className={`menu-root ${className ?? ""}`} ref={root}>
      <button
        ref={btn}
        type="button"
        className="ws-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={label}
        onClick={() => setOpen((o) => !o)}
      >
        {button}
      </button>
      {open && (
        <div
          className="menu-pop"
          role="menu"
          id={id}
          aria-label={label}
          ref={list}
          onKeyDown={onKey}
        >
          {items.map((it) => (
            <div
              key={it.key}
              role={it.kind === "check" ? "menuitemcheckbox" : "menuitemradio"}
              aria-checked={it.checked ?? false}
              aria-disabled={it.disabled || undefined}
              tabIndex={-1}
              className="menu-item"
              onClick={() => {
                if (it.disabled) return;
                it.onSelect();
                if (!stayOpen) {
                  setOpen(false);
                  btn.current?.focus();
                }
              }}
              onKeyDown={(e) => {
                if (e.key !== "Enter" && e.key !== " ") return;
                e.preventDefault();
                if (it.disabled) return;
                it.onSelect();
                if (!stayOpen) {
                  setOpen(false);
                  btn.current?.focus();
                }
              }}
            >
              {it.icon && <span className="menu-item__icon">{it.icon}</span>}
              <span className="menu-item__label">{it.label}</span>
              {it.hint && <span className="menu-item__hint">{it.hint}</span>}
            </div>
          ))}
          {footer && <div className="menu-foot">{footer}</div>}
        </div>
      )}
    </div>
  );
}
