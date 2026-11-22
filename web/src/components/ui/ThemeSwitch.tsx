"use client";

import { useEffect, useState } from "react";

import { getThemeChoice, setThemeChoice, type ThemeChoice } from "@/lib/theme";

const OPTIONS: { value: ThemeChoice; label: string }[] = [
  { value: "system", label: "Auto" },
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
];

/** Auto (follow the device), Dark or Light; the choice is kept on this device. */
export function ThemeSwitch() {
  const [choice, setChoice] = useState<ThemeChoice>("system");
  useEffect(() => setChoice(getThemeChoice()), []);
  return (
    <div className="theme-switch" role="group" aria-label="Theme">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={choice === o.value}
          onClick={() => {
            setThemeChoice(o.value);
            setChoice(o.value);
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
