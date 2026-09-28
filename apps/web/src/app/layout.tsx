import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Script from "next/script";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], display: "swap", variable: "--font-inter" });

export const metadata: Metadata = { title: "SkillSprint AI", description: "Training and onboarding workspace" };

// Applies the saved theme before first paint to avoid a light/dark flash.
const themeScript = `try{if(localStorage.getItem("theme")==="dark")document.documentElement.classList.add("dark")}catch(e){}`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en" className={inter.variable} suppressHydrationWarning>
    <body><Script id="theme-init" strategy="beforeInteractive">{themeScript}</Script>{children}</body>
  </html>;
}
