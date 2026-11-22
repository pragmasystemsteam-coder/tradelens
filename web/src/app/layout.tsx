import "./globals.css";

import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import type { ReactNode } from "react";

import { THEME_INIT_SCRIPT } from "@/lib/theme";

// Archivo's width axis runs from condensed (scores, prices) to expanded (headlines); IBM Plex
// Sans is the reading face. Both are variable Latin files shipped in src/fonts (SIL Open Font
// License, see src/fonts/README.md), so builds never contact Google Fonts: its width-axis URLs
// have no file extension and broke next/font/google on CI.
const archivo = localFont({
  src: "../fonts/archivo-latin-var.woff2",
  weight: "100 900",
  style: "normal",
  declarations: [{ prop: "font-stretch", value: "62% 125%" }],
  variable: "--font-archivo",
  display: "swap",
});
const plex = localFont({
  src: "../fonts/ibm-plex-sans-latin-var.woff2",
  weight: "100 700",
  style: "normal",
  variable: "--font-plex",
  display: "swap",
});

export const metadata: Metadata = {
  title: "TradeLens · Smart Money setups, found and explained",
  description:
    "TradeLens scans forex pairs and commodities for Smart Money Concepts setups, scores them across four timeframes and explains each score in plain English.",
};
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0d1520" },
    { media: "(prefers-color-scheme: light)", color: "#f2f5f8" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${archivo.variable} ${plex.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
