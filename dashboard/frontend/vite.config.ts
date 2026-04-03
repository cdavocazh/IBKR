import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  base: '/IBKR_KZ/',
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/IBKR_KZ/api': {
        target: `http://localhost:${process.env.VITE_API_PORT || 8888}`,
        rewrite: (path) => path.replace(/^\/IBKR_KZ/, ''),
      },
      '/IBKR_KZ/ws': {
        target: `ws://localhost:${process.env.VITE_API_PORT || 8888}`,
        ws: true,
        rewrite: (path) => path.replace(/^\/IBKR_KZ/, ''),
      },
    },
  },
})
