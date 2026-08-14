// Applies admin-configured branding colors on top of the built-in Fluent
// palette defined in index.css. The CSS custom properties there are raw
// "H S% L%" triplets (consumed as hsl(var(--primary)) by Tailwind), not
// hex — hexToHslTriplet converts an admin-entered #RRGGBB into that exact
// shape so this can write directly onto document.documentElement.style,
// overriding the stylesheet value without touching index.css itself.

// Matches index.css's :root --primary (light mode default) — shown as the
// placeholder/fallback in the Appearance color pickers so an unset field
// visibly starts at the current built-in color, not black/blank.
export const DEFAULT_PRIMARY_COLOR = "#0F6CBD";
export const DEFAULT_ACCENT_COLOR = "#0F6CBD";

function hexToHslTriplet(hex: string): string | null {
  const match = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.exec(hex);
  if (!match || !match[1]) return null;
  let normalized = match[1];
  if (normalized.length === 3) {
    normalized = normalized
      .split("")
      .map((c) => c + c)
      .join("");
  }
  const r = parseInt(normalized.slice(0, 2), 16) / 255;
  const g = parseInt(normalized.slice(2, 4), 16) / 255;
  const b = parseInt(normalized.slice(4, 6), 16) / 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;

  if (max === min) {
    return `0 0% ${Math.round(l * 100)}%`;
  }

  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  switch (max) {
    case r:
      h = (g - b) / d + (g < b ? 6 : 0);
      break;
    case g:
      h = (b - r) / d + 2;
      break;
    default:
      h = (r - g) / d + 4;
  }
  h *= 60;

  return `${Math.round(h)} ${Math.round(s * 100)}% ${Math.round(l * 100)}%`;
}

/**
 * Overrides --primary/--accent on the document root with admin-configured
 * colors. Pass null for either to fall back to index.css's built-in
 * value (removes the inline override rather than setting a specific
 * color) — lets an admin clear a customization back to default.
 */
export function applyBrandingColors(primaryColor: string | null, accentColor: string | null): void {
  const root = document.documentElement;
  const primaryHsl = primaryColor ? hexToHslTriplet(primaryColor) : null;
  const accentHsl = accentColor ? hexToHslTriplet(accentColor) : null;

  if (primaryHsl) {
    root.style.setProperty("--primary", primaryHsl);
    root.style.setProperty("--ring", primaryHsl);
  } else {
    root.style.removeProperty("--primary");
    root.style.removeProperty("--ring");
  }

  if (accentHsl) {
    root.style.setProperty("--accent", accentHsl);
  } else {
    root.style.removeProperty("--accent");
  }
}
