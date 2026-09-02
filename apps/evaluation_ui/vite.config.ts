import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "^/review-api": {
        target: "http://localhost:8100",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/review-api/, ""),
      },
      "^/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
