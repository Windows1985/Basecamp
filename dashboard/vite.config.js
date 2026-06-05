import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/latest": "http://localhost:5000",
      "/history": "http://localhost:5000",
      "/log":     "http://localhost:5000",
    },
  },
});
