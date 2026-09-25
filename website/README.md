# ClamUI Website

Marketing site for [ClamUI](https://github.com/linx-systems/clamui), published at **https://clamui.com**.

Built with [Astro](https://astro.build) + [Tailwind CSS](https://tailwindcss.com). Static output is built and deployed to GitHub Pages by `.github/workflows/deploy-website.yml`.

## Local development

```bash
cd website
bun install --frozen-lockfile
bun run dev        # http://localhost:4321
```

The `prebuild` / `predev` scripts sync the logo and screenshots from the repository root into `public/`; do not edit those generated copies. In particular, `screenshots/ClamUI-Social-Preview-1280x640.png` is copied to `public/og-image.png` for social metadata.

## Checking and building

```bash
bun run check
bun run build
bun run preview
```

## Deploying

Pushes to `master` that affect website sources, workflow configuration, screenshots, or icons trigger `deploy-website`; published releases, a weekly schedule, and manual dispatch do too. The workflow runs `bun run build`, uploads `website/dist` as a GitHub Pages artifact, and deploys that artifact through GitHub Actions.

**One-time setup:**

1. Repo → Settings → Pages: Source = *GitHub Actions*, Custom domain = `clamui.com`, Enforce HTTPS = on (enable after DNS propagates).
2. DNS at the registrar:
   - `clamui.com` A records: `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`
   - `clamui.com` AAAA records: `2606:50c0:8000::153`, `2606:50c0:8001::153`, `2606:50c0:8002::153`, `2606:50c0:8003::153`
   - `www.clamui.com` CNAME → `linx-systems.github.io`
3. `public/CNAME` contains `clamui.com` so the custom-domain setting survives deploys.

## Structure

```
website/
├── scripts/copy-assets.mjs    # syncs logo + screenshots from repo root
├── public/                    # static, unprocessed assets
├── src/
│   ├── layouts/Base.astro     # <head>, OG/Twitter, theme bootstrap
│   ├── pages/index.astro      # landing page composition
│   ├── components/            # Hero, FeatureRow, InstallTabs, ...
│   ├── content/features.ts    # feature copy
│   └── styles/global.css      # Tailwind + custom utilities
└── astro.config.mjs
```
