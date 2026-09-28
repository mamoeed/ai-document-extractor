import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` proxies /api to a backend on localhost:8000 (VITE_API_PROXY to override).
export default defineConfig({
  plugins: [react()],
  build: { chunkSizeWarningLimit: 1000 }, // CodeMirror is most of the bundle
  server: {
    proxy: {
      "/api": process.env.VITE_API_PROXY ?? "http://localhost:8000",
    },
  },
});
