import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
      '@deck.gl/core': path.resolve(__dirname, '__mocks__/@deck.gl/core.ts'),
      '@deck.gl/layers': path.resolve(__dirname, '__mocks__/@deck.gl/layers.ts'),
    },
  },
});
