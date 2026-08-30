import { defineConfig } from "astro/config";

// Project pages serve from a subpath, so every internal link has to carry the
// base. Use the `href()` helper in src/lib/data.ts rather than writing "/…"
// paths by hand — see the note there.
export default defineConfig({
  site: "https://ifyoumakeit.github.io",
  base: "/kingston-historic-data",
  build: { format: "directory" },
  trailingSlash: "always",
});
