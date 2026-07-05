import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies API + media to Flask so the app is same-origin
// (session cookie: SameSite=Lax; kickoff decision 11). In production, Flask
// serves the built client from the same origin.
const apiTarget = process.env.API_PROXY_TARGET || 'http://api:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': apiTarget,
      '/media': apiTarget,
      '/healthz': apiTarget,
    },
  },
})
