const HEX_PATTERN = /^#[0-9a-f]{6}$/i;

function darken(hex: string, factor: number): string {
  const channels = [1, 3, 5].map((start) => {
    const value = Math.round(parseInt(hex.slice(start, start + 2), 16) * factor);
    return Math.max(0, Math.min(255, value)).toString(16).padStart(2, "0");
  });
  return `#${channels.join("")}`;
}

export function applyAccentColor(hex: string): void {
  if (!HEX_PATTERN.test(hex)) {
    return;
  }
  const root = document.documentElement;
  root.style.setProperty("--accent", hex);
  root.style.setProperty("--accent-hover", darken(hex, 0.86));
}
