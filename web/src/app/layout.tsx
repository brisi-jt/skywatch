import type { Metadata } from "next";
import { Atkinson_Hyperlegible, Bricolage_Grotesque, Spline_Sans_Mono } from "next/font/google";

import { Providers } from "@/components/providers";
import { Shell } from "@/components/shell";

import "./globals.css";

const body = Atkinson_Hyperlegible({
  weight: ["400", "700"],
  style: ["normal", "italic"],
  subsets: ["latin"],
  variable: "--font-body",
});

const display = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-display",
});

const readout = Spline_Sans_Mono({
  subsets: ["latin"],
  variable: "--font-readout",
});

export const metadata: Metadata = {
  title: "skywatch station",
  description: "A listening post for the airband above your house.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-GB" suppressHydrationWarning>
      <body className={`${body.variable} ${display.variable} ${readout.variable}`}>
        <Providers>
          <Shell>{children}</Shell>
        </Providers>
      </body>
    </html>
  );
}
