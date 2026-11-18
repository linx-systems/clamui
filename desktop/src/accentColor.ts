const HEX_PATTERN = /^#[0-9a-f]{6}$/i;
const ACCENT_PROPERTIES = ["--accent", "--accent-hover", "--focus"] as const;

type StyleTarget = { style: Pick<CSSStyleDeclaration, "setProperty" | "removeProperty"> };

function darken(hex: string, factor: number): string {
  const channels = [1, 3, 5].map((start) => {
    const value = Math.round(parseInt(hex.slice(start, start + 2), 16) * factor);
    return Math.max(0, Math.min(255, value)).toString(16).padStart(2, "0");
  });
  return `#${channels.join("")}`;
}

/**
 * Applies the system accent color, or restores the stylesheet defaults when the
 * system reports no accent (`null`). Malformed values leave the current colors.
 */
export function applyAccentColor(accent: string | null, root: StyleTarget = document.documentElement): void {
  if (accent === null) {
    for (const property of ACCENT_PROPERTIES) {
      root.style.removeProperty(property);
    }
    return;
  }
  if (!HEX_PATTERN.test(accent)) {
    return;
  }
  root.style.setProperty("--accent", accent);
  root.style.setProperty("--accent-hover", darken(accent, 0.86));
  root.style.setProperty("--focus", accent);
}
