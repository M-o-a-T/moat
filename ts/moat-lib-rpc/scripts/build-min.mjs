import esbuild from 'esbuild';
import { readFileSync } from 'node:fs';

const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf-8'));

const banner = `/**
 * @moat/lib-rpc v${pkg.version}
 * Copyright (c) 2024-2026 Matthias Urlichs
 * MIT License
 */`;

await esbuild.build({
  entryPoints: ['src/index.ts'],
  bundle: true,
  minify: true,
  sourcemap: true,
  platform: 'node',
  target: 'es2022',
  format: 'esm',
  outfile: 'dist/moat-lib-rpc.min.js',
  banner: { js: banner },
  legalComments: 'none',
});

console.log('✓ dist/moat-lib-rpc.min.js');
