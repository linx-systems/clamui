import { createMermaidRenderer } from "mermaid-isomorphic";
import { defineHastPlugin } from "satteri";

const LIGHT_THEME = "default";
const DARK_THEME = "dark";

function hasMermaidClass(className) {
  if (Array.isArray(className)) {
    return className.includes("language-mermaid");
  }

  return typeof className === "string" && className.split(/\s+/).includes("language-mermaid");
}

function getMermaidSource(node, ctx) {
  const code = node.children.find(
    (child) =>
      child.type === "element" && child.tagName === "code" && hasMermaidClass(child.properties?.className),
  );

  return code ? ctx.textContent(code) : undefined;
}

function addThemeMarker(svg, theme) {
  const marked = svg.replace(/<svg\b/, `<svg data-mermaid-theme="${theme}"`);

  if (marked === svg) {
    throw new Error("Mermaid renderer returned SVG without a root element.");
  }

  return marked;
}

function renderFailure(result, fileURL) {
  const location = fileURL ? ` in ${fileURL.pathname}` : "";
  const reason = result.reason instanceof Error ? result.reason.message : String(result.reason);

  return new Error(`Failed to render Mermaid diagram${location}: ${reason}`);
}

export function mermaidSatteriPlugin({ source }) {
  if (!source.includes("mermaid")) {
    return undefined;
  }

  const diagrams = [];
  const render = createMermaidRenderer();

  return defineHastPlugin({
    name: "clamui-build-time-mermaid",
    element: {
      filter: ["pre"],
      visit(node, ctx) {
        const source = getMermaidSource(node, ctx);

        if (source !== undefined) {
          diagrams.push({ node, source });
        }
      },
    },
    async after(_root, ctx) {
      if (diagrams.length === 0) {
        return;
      }

      const sources = diagrams.map(({ source }) => source);
      const [lightResults, darkResults] = await Promise.all([
        render(sources, {
          mermaidConfig: { securityLevel: "strict", theme: LIGHT_THEME },
          prefix: "mermaid-light",
        }),
        render(sources, {
          mermaidConfig: { securityLevel: "strict", theme: DARK_THEME },
          prefix: "mermaid-dark",
        }),
      ]);

      for (const [index, { node }] of diagrams.entries()) {
        const light = lightResults[index];
        const dark = darkResults[index];

        if (light.status === "rejected") {
          throw renderFailure(light, ctx.fileURL);
        }
        if (dark.status === "rejected") {
          throw renderFailure(dark, ctx.fileURL);
        }

        ctx.replaceNode(node, {
          type: "element",
          tagName: "div",
          properties: { className: ["mermaid-diagram"] },
          children: [
            { type: "raw", value: addThemeMarker(light.value.svg, "light") },
            { type: "raw", value: addThemeMarker(dark.value.svg, "dark") },
          ],
        });
      }
    },
  });
}
