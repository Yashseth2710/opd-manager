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
];

export default config;
