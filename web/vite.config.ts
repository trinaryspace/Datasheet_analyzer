/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/**
 * Vite + Vitest configuration for the workbench frontend.
 *
 * Written once by ticket 00; the five frontend tickets add files, not
 * configuration. Two things here are contracts rather than preferences:
 *
 * - `build.outDir` is `dist`, which is exactly where `app/static.py` looks
 *   when it decides whether a built frontend exists.
 * - `test.include` reaches `../tests/web`, because the repo keeps its tests
 *   in one tree; a frontend ticket drops `tests/web/<screen>.test.tsx` there
 *   and `npm test` picks it up with no config change.
 *
 * Nothing may be fetched from a CDN at runtime (the app is local-only and
 * must work with no internet), so every asset — the PDF.js worker included —
 * is bundled.
 */
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    port: 5173,
    strictPort: false,
    // `npm run dev` serves the UI while `dsa serve` serves the API; the proxy
    // makes the two look like one origin, so the client never needs a base URL.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
    fs: {
      allow: ['..'],
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', '../tests/web/**/*.test.{ts,tsx}'],
    css: false,
  },
});
