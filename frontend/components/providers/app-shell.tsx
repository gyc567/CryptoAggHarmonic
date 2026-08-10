"use client";

import { usePathname } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";

const PUBLIC_PATHS = ["/login", "/auth/callback"];

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const { user, profile } = useAuth();

  const isPublic = PUBLIC_PATHS.some((p) => pathname?.startsWith(p));
  const showSidebar = !isPublic && !!user;

  return (
    <div className="flex min-h-screen">
      {showSidebar && <Sidebar profile={profile} />}
      <div className="flex flex-1 flex-col">
        {showSidebar && <Topbar title={getPageTitle(pathname)} profile={profile} />}
        <main className={showSidebar ? "flex-1 overflow-auto" : "flex-1"}>
          {children}
        </main>
      </div>
    </div>
  );
}

function getPageTitle(pathname: string | null): string {
  if (pathname?.startsWith("/rsi-strategy")) return "趋势RSI策略";
  if (pathname?.startsWith("/dashboard")) return "分析工作台";
  if (pathname?.startsWith("/position")) return "仓位管理";
  if (pathname?.startsWith("/vibe")) return "AI 交易助手";
  if (pathname?.startsWith("/history")) return "历史记录";
  if (pathname?.startsWith("/settings")) return "账户设置";
  if (pathname?.startsWith("/admin")) return "管理员";
  return "CryptoAgg";
}
