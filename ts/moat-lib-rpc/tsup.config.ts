import { defineConfig } from 'tsup';

export default defineConfig({
  entry: ['src/index.ts', 'src/codec.ts', 'src/transport/ws.ts', 'src/transport/tcp.ts'],
  format: ['esm', 'cjs'],
  dts: true,
  splitting: false,
  sourcemap: true,
  clean: true,
  treeshake: true,
  target: 'es2022',
  platform: 'node',
  outExtension: ({ format }) => ({
    js: format === 'esm' ? '.js' : '.cjs',
    dts: format === 'esm' ? '.d.ts' : '.d.cts',
  }),
});
