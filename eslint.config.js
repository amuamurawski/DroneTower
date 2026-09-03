"use strict";

// Płaska konfiguracja ESLint dla kart Lovelace (klasyczne skrypty przeglądarki)
// i pomocników testowych node:test. Vendored Leaflet oraz workspace analizy APK
// są ignorowane w całości.

const js = require("@eslint/js");
const globals = require("globals");

module.exports = [
  {
    ignores: [
      "node_modules/**",
      // Vendored kod — nie nasz styl, nie lintujemy.
      "custom_components/dronetower_amu/frontend/leaflet/**",
      // Workspace analizy APK (gitignored, ale istnieje lokalnie).
      "work/**",
      "extracted_xapk/**",
      "jadx_tool/**",
      "tools/**",
      "docs/**",
    ],
  },

  // Karty frontendowe: KLASYCZNE skrypty przeglądarki (bez import/export).
  {
    files: ["custom_components/dronetower_amu/frontend/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
      },
    },
    rules: {
      ...js.configs.recommended.rules,
      // Literówki w identyfikatorach mają być błędem, nie ostrzeżeniem.
      "no-undef": "error",
      // Karty nie logują w pętli renderu; jednorazowy banner "loaded" ma
      // jawny inline-disable.
      "no-console": "error",
      "no-unused-vars": [
        "error",
        {
          // Konwencja w kartach: celowo nieużywane wartości mają prefiks "_".
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
      // Skrypt klasyczny współdzieli globalny zakres strony — import/export
      // to błąd składni w przeglądarce przy add_extra_js_url.
      "no-restricted-syntax": [
        "error",
        {
          selector: "ImportDeclaration, ExportNamedDeclaration, ExportDefaultDeclaration, ExportAllDeclaration",
          message: "Karty są ładowane jako klasyczne skrypty — bez import/export.",
        },
      ],
    },
  },

  // Harness testowy: moduły ES uruchamiane w Node.
  {
    files: ["tests/frontend/**/*.mjs"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        ...globals.node,
      },
    },
    rules: {
      ...js.configs.recommended.rules,
      "no-undef": "error",
    },
  },

  // Sama konfiguracja (CommonJS).
  {
    files: ["eslint.config.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "commonjs",
      globals: {
        ...globals.node,
      },
    },
    rules: js.configs.recommended.rules,
  },
];
