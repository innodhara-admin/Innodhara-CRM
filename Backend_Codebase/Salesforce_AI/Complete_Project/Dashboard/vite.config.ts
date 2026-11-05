import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // Change #8 mounts the bundle at /dashboard, not at the server root. A
  // default base of "/" emits asset URLs that 404 there.
  base: "/dashboard/",
  build: { outDir: "dist" },
});
