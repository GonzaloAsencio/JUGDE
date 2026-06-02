import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import jsxA11y from "eslint-plugin-jsx-a11y";

// jsx-a11y recommended rules, downgraded to `warn` for Capa 0 (safety net).
// They get promoted to `error` at the end of Capa 1 (accessibility). Rule
// options (the tail of an `["error", opts]` tuple) are preserved.
const jsxA11yWarn = Object.fromEntries(
  Object.entries(jsxA11y.flatConfigs.recommended.rules).map(([rule, value]) => [
    rule,
    Array.isArray(value) ? ["warn", ...value.slice(1)] : "warn",
  ]),
);

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // The jsx-a11y plugin is already registered by eslint-config-next; we only
  // raise its rule coverage to the full recommended set (as warnings here).
  {
    rules: jsxA11yWarn,
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
