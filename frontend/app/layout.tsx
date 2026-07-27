import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { AppShell } from "@/components/providers/app-shell";
import { ChunkErrorBoundary } from "@/components/error-boundary/chunk-error-boundary";

const geistSans = localFont({
  src: "./fonts/GeistVF.woff",
  variable: "--font-geist-sans",
  weight: "100 900",
});

const geistMono = localFont({
  src: "./fonts/GeistMonoVF.woff",
  variable: "--font-geist-mono",
  weight: "100 900",
});

export const metadata: Metadata = {
  title: "Pyharmonics - 谐波形态分析",
  description: "邀请制谐波形态与背离分析 SaaS",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <ChunkErrorBoundary>
          <AppShell>{children}</AppShell>
        </ChunkErrorBoundary>
      </body>
    </html>
  );
}
