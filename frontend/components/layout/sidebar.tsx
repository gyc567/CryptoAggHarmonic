"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Clock,
  Settings,
  Shield,
  Sparkles,
  Star,
  TrendingUp,
  Wallet,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { UserProfile } from "@/types";

interface SidebarProps {
  profile: UserProfile | null;
  className?: string;
}

const NAV_ITEMS = [
  { href: "/watchlist", label: "自选币种", icon: Star },
  { href: "/rsi-strategy", label: "趋势RSI策略", icon: TrendingUp },
  { href: "/dashboard", label: "分析", icon: BarChart3 },
  { href: "/position", label: "仓位", icon: Wallet },
  { href: "/vibe", label: "AI 交易助手", icon: Sparkles },
  { href: "/history", label: "历史记录", icon: Clock },
  { href: "/settings", label: "设置", icon: Settings },
];

export function Sidebar({ profile, className }: SidebarProps) {
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "hidden md:flex flex-col w-64 h-screen sticky top-0 border-r border-border-subtle bg-card/50 backdrop-blur-xl",
        className
      )}
    >
      <div className="flex items-center gap-3 px-5 h-16 border-b border-border-subtle">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-cy to-purple text-white shadow-glow-sm">
          <Zap className="h-5 w-5" />
        </div>
        <span className="text-lg font-bold text-gradient">Pyharmonics</span>
      </div>

      <nav className="flex-1 space-y-1 p-4">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn("nav-item", active && "nav-item-active")}
            >
              <Icon className="h-[18px] w-[18px]" />
              {item.label}
            </Link>
          );
        })}

        {profile?.role === "admin" && (
          <Link
            href="/admin"
            className={cn(
              "nav-item mt-4",
              pathname === "/admin" && "nav-item-active"
            )}
          >
            <Shield className="h-[18px] w-[18px]" />
            管理员
          </Link>
        )}
      </nav>

      <div className="p-4 border-t border-border-subtle">
        <div className="rounded-xl bg-elevated px-4 py-3 text-xs text-muted-foreground">
          <p className="font-medium text-foreground">Beta 版本</p>
          <p className="mt-1">仅供技术研究，不构成投资建议。</p>
        </div>
      </div>
    </aside>
  );
}
