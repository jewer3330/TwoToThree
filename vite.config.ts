import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    watch: { ignored: ['**/.local/**', '**/data/**', '**/dist/**', '**/output/**', '**/logs/**'] },
    proxy: { '/api': 'http://127.0.0.1:8000', '/data': 'http://127.0.0.1:8000' },
  },
  preview: {
    proxy: { '/api': 'http://127.0.0.1:8000', '/data': 'http://127.0.0.1:8000' },
  },
});
