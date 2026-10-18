// One ES module bundle for the panel (decision L62), and the vitest setup.
//
// The bundle lands inside the integration, where the core serves it once `panel.py`
// registers the panel; that path is ignored by git until the panel and its CI check
// exist. Tests run in a DOM environment against a fake `hass` (test/fake-hass.ts).

import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const OUT_DIR = fileURLToPath(new URL("../custom_components/device_routines/frontend/dist", import.meta.url));

export default defineConfig({
  build: {
    outDir: OUT_DIR,
    emptyOutDir: true,
    copyPublicDir: false,
    target: "es2022",
    minify: true,
    sourcemap: false,
    // Keep the `@license` headers of the bundled libraries (Lit is BSD-3-Clause).
    rolldownOptions: { output: { comments: { legal: true } } },
    lib: {
      entry: fileURLToPath(new URL("src/device-routines-panel.ts", import.meta.url)),
      formats: ["es"],
      fileName: () => "device-routines-panel.js",
    },
  },
  test: {
    environment: "happy-dom",
    include: ["test/**/*.test.ts"],
  },
});
