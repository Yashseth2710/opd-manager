import next from "eslint-config-next";

const config = [
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "backend/**",
      "alembic/**",
      "scripts/**",
      ".venv/**",
    ],
  },
  ...next,
  {
    // Playwright hands a fixture its `use` function, which the React rules
    // read as a hook called outside a component.
    files: ["e2e/**/*.ts", "playwright.config.ts"],
    rules: { "react-hooks/rules-of-hooks": "off" },
  },
];

export default config;
