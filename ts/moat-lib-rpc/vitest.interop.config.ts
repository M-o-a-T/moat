import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['test/interop/**/*.test.ts'],
    environment: 'node',
    timeout: 30000,
  },
});
