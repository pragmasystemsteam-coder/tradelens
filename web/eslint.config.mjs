// ESLint flat config: Next.js core web vitals + TypeScript, Prettier owns formatting.
// Feature-boundary rules (eslint-plugin-boundaries) arrive in Increment 2 (ADR-0001 section 4).
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const config = [
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
  ...compat.extends("next/core-web-vitals", "next/typescript", "prettier"),
];

export default config;
