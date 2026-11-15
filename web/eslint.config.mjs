// ESLint flat config: Next.js core web vitals + TypeScript, Prettier owns formatting.
// Feature boundaries (ADR-0001 section 4): app is thin, features are isolated from each
// other, components/ui and lib are leaves.
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { FlatCompat } from "@eslint/eslintrc";
import boundaries from "eslint-plugin-boundaries";

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const config = [
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts", "playwright-report/**", "test-results/**"] },
  ...compat.extends("next/core-web-vitals", "next/typescript", "prettier"),
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: { boundaries },
    settings: {
      "import/resolver": { typescript: { alwaysTryTypes: true } },
      "boundaries/elements": [
        { type: "app", pattern: "src/app/**" },
        { type: "feature", pattern: "src/features/*", capture: ["feature"] },
        { type: "layout", pattern: "src/components/layout/**" },
        { type: "ui", pattern: "src/components/ui/**" },
        { type: "lib", pattern: "src/lib/**" },
      ],
    },
    rules: {
      "boundaries/dependencies": [
        "error",
        {
          default: "disallow",
          policies: [
            { from: { element: { type: "app" } }, allow: [{ to: { element: { type: "feature" } } }, { to: { element: { type: "layout" } } }, { to: { element: { type: "ui" } } }, { to: { element: { type: "lib" } } }] },
            { from: { element: { type: "feature" } }, allow: [{ to: { element: { type: "feature", captured: { feature: "{{from.captured.feature}}" } } } }, { to: { element: { type: "layout" } } }, { to: { element: { type: "ui" } } }, { to: { element: { type: "lib" } } }] },
            { from: { element: { type: "layout" } }, allow: [{ to: { element: { type: "ui" } } }, { to: { element: { type: "lib" } } }] },
            { from: { element: { type: "ui" } }, allow: [{ to: { element: { type: "ui" } } }, { to: { element: { type: "lib" } } }] },
            { from: { element: { type: "lib" } }, allow: [{ to: { element: { type: "lib" } } }] },
          ],
        },
      ],
    },
  },
];

export default config;
