import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// base "./" so the built dist/ works from any path (repo subfolder, GitHub Pages, nginx…)
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
});
