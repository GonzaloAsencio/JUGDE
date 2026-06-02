import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import jsxA11y from "eslint-plugin-jsx-a11y";

// jsx-a11y recommended rules, promoted to `error` at the close of Capa 1
// (accessibility). Rule options (the tail of an `["error", opts]` tuple) are
// preserved. `label-has-for` is deprecated — superseded by
// `label-has-associated-control`, which eslint-config-next already enforces —
// and false-positives on valid htmlFor/id association, so it is turned off.
const jsxA11yRules = {
  ...Object.fromEntries(
    Object.entries(jsxA11y.flatConfigs.recommended.rules).map(([rule, value]) => [
      rule,
      Array.isArray(value) ? ["error", ...value.slice(1)] : "error",
    ]),
  ),
  "jsx-a11y/label-has-for": "off",
};

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // The jsx-a11y plugin is already registered by eslint-config-next; we only
  // raise its rule coverage to the full recommended set (as errors).
  {
    rules: jsxA11yRules,
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
