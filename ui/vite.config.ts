import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Groundctl Phase 8 web UI. Dev-server proxy forwards /api (every resource
// router is mounted under that one prefix server-side — see app/main.py)
// to a locally running uvicorn instance on :8000 so `npm run dev` (:5173)
// can be used against a real backend without CORS. Build output uses
// Vite's default ui/dist — scripts/lib/app.sh's build_ui() is the
// established convention that syncs ui/dist -> app/static (rm -rf +
// cp -a), which app/main.py mounts as the SPA if the directory exists. Do
// not build directly to ../app/static here; that would bypass build_ui's
// rm -rf-before-copy step and could leave stale files from a previous
// build mixed in.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        // Same-origin-shaped proxying (host/port change but path doesn't)
        // means cookies set by the backend (e.g. the ui-login refresh
        // cookie) pass through unmodified — no cookieDomainRewrite /
        // cookiePathRewrite needed since the Set-Cookie Domain attribute
        // is unset and Path=/api/auth is untouched by this proxy.
      },
    },
  },
});
