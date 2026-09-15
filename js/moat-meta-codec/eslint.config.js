/** @type {import("eslint").Linter.Config} */
export default [
  {
    languageOptions: {
      ecmaVersion: 2024,
      sourceType: "module",
      globals: {
        console: "readonly",
        Buffer: "readonly",
        Date: "readonly",
        Math: "readonly",
        Number: "readonly",
        Object: "readonly",
        Array: "readonly",
        TypeError: "readonly",
        Error: "readonly",
      },
    },
    rules: {
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
    },
  },
  {
    ignores: ["node_modules/", "dist/", "coverage/"],
  },
];
