import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // Set QUIETOFFICE_API to point the dev server at a backend on another port.
        target: process.env.QUIETOFFICE_API ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
