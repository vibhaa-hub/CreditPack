import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves on :5173 and forwards /api to the workbench API (python -m workbench, :8000).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"],
          mui: ["@mui/material", "@emotion/react", "@emotion/styled"],
          icons: ["@mui/icons-material"],
        },
      },
    },
  },
});
