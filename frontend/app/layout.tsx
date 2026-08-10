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
  title: "CryptoAgg - Agent 化加密货币交易策略",
  description: "agent化加密货币交易策略，让天下没有难写的策略",
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
