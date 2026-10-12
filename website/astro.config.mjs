import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import mermaid from "astro-mermaid";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  site: "https://clamui.com",
  base: "/",
  output: "static",
  compressHTML: true,
  integrations: [
    mermaid({
      theme: "default",
      autoTheme: true,
      enableLog: false,
      mermaidConfig: {
        securityLevel: "strict",
      },
    }),
    starlight({
      title: "ClamUI Documentation",
      description: "Install, use, configure, and contribute to ClamUI.",
      logo: {
        src: "./src/assets/logo.svg",
        alt: "ClamUI",
      },
      social: [
        {
          icon: "github",
          label: "ClamUI on GitHub",
          href: "https://github.com/linx-systems/clamui",
        },
      ],
      sidebar: [
        {
          label: "Start here",
          items: ["docs", "docs/installation", "docs/getting-started", "docs/troubleshooting"],
        },
        {
          label: "Guides",
          items: [
            "docs/guides/scanning",
            "docs/guides/profiles",
            "docs/guides/quarantine",
            "docs/guides/scheduling",
            "docs/guides/settings",
            "docs/guides/history",
            "docs/guides/statistics",
            "docs/guides/tray",
            "docs/guides/security-audit",
            "docs/guides/faq",
          ],
        },
        {
          label: "Reference",
          items: [
            "docs/reference/configuration",
            "docs/reference/scan-backends",
            "docs/reference/release-notes",
            "docs/reference/changelog",
          ],
        },
        {
          label: "Contributing",
          items: [
            "docs/contributing/development",
            "docs/contributing/translating",
            "docs/contributing/signing",
            "docs/contributing/architecture",
            "docs/contributing/code-of-conduct",
            "docs/contributing/security",
          ],
        },
      ],
      tableOfContents: {
        minHeadingLevel: 2,
        maxHeadingLevel: 3,
      },
      markdown: {
        processedDirs: [".."],
      },
      customCss: ["./src/styles/starlight.css"],
    }),
  ],
  vite: {
    plugins: [tailwindcss()],
  },
  build: {
    inlineStylesheets: "auto",
  },
});
