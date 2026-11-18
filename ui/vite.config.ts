import { defineConfig } from "vite";

// base "./" so the built files load from disk inside the desktop window.
export default defineConfig({
  base: "./",
  build: { outDir: "dist", emptyOutDir: true, assetsInlineLimit: 0 },
});
