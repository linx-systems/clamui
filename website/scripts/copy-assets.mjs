#!/usr/bin/env node
// Copies shared project assets (logo, screenshots) into website/public/
// so the site has a single source of truth and stays in sync with the app.

import { cp, mkdir, copyFile, access } from "node:fs/promises";
import { constants } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const websiteRoot = resolve(here, "..");
const repoRoot = resolve(websiteRoot, "..");

const tasks = [
  {
    from: resolve(repoRoot, "icons/io.github.linx_systems.ClamUI.svg"),
    to: resolve(websiteRoot, "public/favicon.svg"),
  },
  {
    from: resolve(repoRoot, "icons/io.github.linx_systems.ClamUI.svg"),
    to: resolve(websiteRoot, "src/assets/logo.svg"),
  },
  {
    from: resolve(repoRoot, "screenshots/ClamUI-Social-Preview-1280x640.png"),
    to: resolve(websiteRoot, "public/og-image.png"),
  },
  {
    from: resolve(repoRoot, "screenshots"),
    to: resolve(websiteRoot, "public/screenshots"),
    recursive: true,
  },
];

async function exists(p) {
  try {
    await access(p, constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

for (const t of tasks) {
  if (!(await exists(t.from))) {
    console.warn(`[copy-assets] missing: ${t.from}`);
    continue;
  }
  await mkdir(dirname(t.to), { recursive: true });
  if (t.recursive) {
    await cp(t.from, t.to, { recursive: true });
  } else {
    await copyFile(t.from, t.to);
  }
  console.log(`[copy-assets] ${t.from} -> ${t.to}`);
}
