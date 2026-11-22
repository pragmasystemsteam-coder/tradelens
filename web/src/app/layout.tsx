import "./globals.css";

import type { Metadata, Viewport } from "next";
import { Archivo, IBM_Plex_Sans } from "next/font/google";
import type { ReactNode } from "react";

import { THEME_INIT_SCRIPT } from "@/lib/theme";

// Archivo's width axis runs from condensed (scores, prices) to expanded (headlines); IBM Plex
// Sans is the reading face. next/font self-hosts both at build time (no runtime requests).
const archivo = Archivo({
  subsets: ["latin"],
  axes: ["wdth"],
  variable: "--font-archivo",
  display: "swap",
});
const plex = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
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
