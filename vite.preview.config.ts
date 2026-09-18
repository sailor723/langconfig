import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist-preview',
    rollupOptions: {
      input: 'layout-preview.html',
    },
  },
});
