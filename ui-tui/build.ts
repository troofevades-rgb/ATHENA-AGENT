// Build script that forces react/jsx-dev-runtime → react/jsx-runtime
// so the production build doesn't crash (the production min of
// jsx-dev-runtime stubs jsxDEV to void 0).
import { copyFileSync, mkdirSync } from "node:fs";

const result = await Bun.build({
  entrypoints: ["src/main.tsx"],
  outdir: "dist",
  target: "node",
  naming: "main.js",
  define: {
    "process.env.NODE_ENV": '"production"',
    "process.env.DEV": '"false"',
  },
  plugins: [
    {
      name: "jsx-production",
      setup(build) {
        build.onResolve({ filter: /^react\/jsx-dev-runtime$/ }, () => ({
          path: "react/jsx-runtime",
          namespace: "node_module",
        }));
      },
    },
  ],
});

if (!result.success) {
  console.error("build failed:");
  for (const log of result.logs) console.error(log);
  process.exit(1);
}

// Install to athena/_tui_bundle/
try { mkdirSync("../athena/_tui_bundle", { recursive: true }); } catch {}
copyFileSync("dist/main.js", "../athena/_tui_bundle/main.js");
console.log(`built ${result.outputs[0].path} (${(result.outputs[0].size / 1024).toFixed(0)} KB) → athena/_tui_bundle/main.js`);
