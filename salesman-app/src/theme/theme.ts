/**
 * Design tokens for the Salesman mobile app.
 * Mirrors the light, premium direction used across Stonic's web properties
 * so the app doesn't feel like a different product.
 */
export const colors = {
  bg: "#FFFFFF",
  surface: "#F6F7FA",
  surfaceStrong: "#EEF0F4",
  border: "#E6E8ED",
  borderStrong: "#D5D8E0",
  text: "#0E0F12",
  textMuted: "#565861",
  textDim: "#8B8D97",
  accent: "#3654D6",
  accentHover: "#2A44B8",
  accentDim: "#EEF1FD",
  success: "#0F9D58",
  successDim: "#E8F6EE",
  whatsapp: "#128C4B",
  warning: "#B45309",
  warningDim: "#FFF7E6",
  danger: "#DC2626",
  dangerDim: "#FEF0F0",
  violet: "#6D28D9",
  violetDim: "#F3EEFE",
  white: "#FFFFFF",
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  pill: 999,
} as const;

export const typography = {
  display: { fontSize: 32, fontWeight: "700" as const, letterSpacing: -0.5 },
  title: { fontSize: 22, fontWeight: "700" as const, letterSpacing: -0.3 },
  heading: { fontSize: 17, fontWeight: "600" as const },
  body: { fontSize: 15, fontWeight: "400" as const },
  bodyMedium: { fontSize: 15, fontWeight: "500" as const },
  caption: { fontSize: 13, fontWeight: "400" as const },
  tiny: { fontSize: 11, fontWeight: "600" as const, letterSpacing: 0.8 },
} as const;