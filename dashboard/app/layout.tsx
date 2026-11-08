import type { Metadata } from "next";
import { Geist, Newsreader } from "next/font/google";
import "./globals.css";

// Geist for everything; Newsreader only for page titles and big numbers (design/DESIGN.md).
const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "JobPilot",
  description: "Personal job-application copilot (mock screens)",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${newsreader.variable} h-full antialiased`}>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
