# ClamUI Website

[ClamUI](https://github.com/linx-systems/clamui)'s marketing site and documentation, published at **https://clamui.com**. It uses Astro, Tailwind CSS, and Starlight at `/docs/`; GitHub Pages deploys the static output through `.github/workflows/deploy-website.yml`.

## Work locally

```bash
cd website
bun install --frozen-lockfile
bun run dev
bun run check
bun run build
bun run preview
```

`prebuild` and `predev` synchronize root icons and screenshots into `public/`. Do not edit those generated copies; `screenshots/ClamUI-Social-Preview-1280x640.png` becomes `public/og-image.png`.

## Write documentation

Write every published guide in `src/content/docs/docs/`. Use concise task-focused Markdown or MDX, canonical root-relative `/docs/.../` links, and add a sidebar entry in `astro.config.mjs`. The release reference pages import root `CHANGELOG.md` and `RELEASE_NOTES.md`; do not duplicate their content. Root `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, and `CODE_OF_CONDUCT.md` are GitHub discoverability pointers, not a second documentation tree.

The `/docs/` site uses Starlight for navigation, full-text search, and copyable code blocks without a separate CMS, server, or search service.

## Deployment

Pushes to `master` that affect website sources, workflow configuration, screenshots, or icons trigger `deploy-website`; published releases, a weekly schedule, and manual dispatch do too. The workflow builds `website/dist` and deploys it as a GitHub Pages artifact. One-time Pages/DNS setup remains in repository settings: source GitHub Actions, custom domain `clamui.com`, HTTPS after DNS propagation, GitHub Pages A/AAAA records, `www` CNAME to `linx-systems.github.io`, and `public/CNAME` containing `clamui.com`.

## Structure

```text
website/
├── astro.config.mjs
├── scripts/copy-assets.mjs
├── public/
└── src/
    ├── components/
    ├── content/docs/docs/
    ├── layouts/
    ├── pages/
    └── styles/
```
