// Type-aware lint for the map components. The limits match the repo's Python
// rules (pyproject.toml): complexity <= 8, <= 5 parameters, <= 100 lines per
// function. Formatting is Prettier's job, so its conflicting rules are off.
import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import { defineConfig } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["node_modules/", "dist/"] },
  js.configs.recommended,
  tseslint.configs.strictTypeChecked,
  {
    languageOptions: {
      globals: globals.browser,
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      "@typescript-eslint/no-floating-promises": "error",
      complexity: ["error", 8],
      "max-params": ["error", 5],
      "max-lines-per-function": ["error", { max: 100, skipBlankLines: true, skipComments: true }],
    },
  },
  // These run in Node and are not part of tsconfig's project.
  {
    files: ["eslint.config.js", "build.js"],
    extends: [tseslint.configs.disableTypeChecked],
    languageOptions: { globals: globals.node },
  },
  prettier,
);
