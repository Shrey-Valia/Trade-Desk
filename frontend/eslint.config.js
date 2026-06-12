// Flat config for ESLint 9 — `npm run lint` was broken since the v9
// upgrade (no eslint.config.js; the legacy .eslintrc era predates this
// repo). Standard Vite + React + TS setup from the installed plugins.
import js from "@eslint/js";
import tsParser from "@typescript-eslint/parser";
import tsPlugin from "@typescript-eslint/eslint-plugin";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";

export default [
  { ignores: ["dist/**", "node_modules/**", "*.config.js", "*.config.ts"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      parser: tsParser,
      ecmaVersion: 2022,
      sourceType: "module",
      globals: globals.browser,
    },
    plugins: {
      "@typescript-eslint": tsPlugin,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...js.configs.recommended.rules,
      ...tsPlugin.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      // TS owns undefined-name checking; the JS rule false-positives on
      // type names and globals like React.
      "no-undef": "off",
      // Stylistic noise we don't want blocking the build.
      "@typescript-eslint/no-explicit-any": "off",
      "react-refresh/only-export-components": "off",
      "no-empty": ["error", { allowEmptyCatch: true }],
    },
  },
];
