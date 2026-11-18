import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// One self-contained index.html: all JS, CSS and fonts are inlined, so the desktop window
// never depends on the local server's MIME types or paths for code and styles.
// (Large assets like models/monkey.glb and prototype images stay as separate files.)
export default defineConfig({
  base: "./",
  plugins: [viteSingleFile({ removeViteModuleLoader: true })],
  build: { outDir: "dist", emptyOutDir: true, assetsInlineLimit: 100_000_000, cssCodeSplit: false },
});
