import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Sidebar } from "@/components/layout/sidebar";
import type { UserProfile } from "@/types";

// usePathname is mocked per-test so we can assert active-state behavior.
const mockUsePathname = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => mockUsePathname(),
}));

const baseProfile: UserProfile = {
  id: "user-1",
  email: "u@example.com",
  role: "user",
  status: "active",
  daily_quota: 100,
  used_quota: 0,
};

describe("Sidebar", () => {
  it("renders all 7 primary nav items with the 谐波分析 dashboard label", () => {
    mockUsePathname.mockReturnValue("/watchlist");

    render(<Sidebar profile={baseProfile} />);

    // The label change that motivated this test — 谐波分析 (not 分析)
    // must be present and linked to /dashboard.
    const dashboardLink = screen.getByRole("link", { name: /谐波分析/ });
    expect(dashboardLink).toBeInTheDocument();
    expect(dashboardLink).toHaveAttribute("href", "/dashboard");

    // All other nav items remain unchanged.
    expect(screen.getByRole("link", { name: /自选币种/ })).toHaveAttribute(
      "href",
      "/watchlist"
    );
    expect(
      screen.getByRole("link", { name: /趋势RSI策略/ })
    ).toHaveAttribute("href", "/rsi-strategy");
    expect(screen.getByRole("link", { name: /仓位/ })).toHaveAttribute(
      "href",
      "/position"
    );
    expect(
      screen.getByRole("link", { name: /AI 交易助手/ })
    ).toHaveAttribute("href", "/vibe");
    expect(screen.getByRole("link", { name: /历史记录/ })).toHaveAttribute(
      "href",
      "/history"
    );
    expect(screen.getByRole("link", { name: /设置/ })).toHaveAttribute(
      "href",
      "/settings"
    );
    expect(
      screen.getAllByRole("link").filter((l) => l.getAttribute("href") === "/dashboard").length
    ).toBe(1);
  });

  it("does not show the admin link for non-admin profiles", () => {
    mockUsePathname.mockReturnValue("/dashboard");

    render(<Sidebar profile={baseProfile} />);

    expect(screen.queryByRole("link", { name: /管理员/ })).not.toBeInTheDocument();
  });

  it("shows the admin link when profile.role is admin", () => {
    mockUsePathname.mockReturnValue("/admin");
    const adminProfile: UserProfile = {
      ...baseProfile,
      role: "admin",
    };

    render(<Sidebar profile={adminProfile} />);

    const adminLink = screen.getByRole("link", { name: /管理员/ });
    expect(adminLink).toHaveAttribute("href", "/admin");
  });

  it("marks the nav-item matching the current pathname as active", () => {
    mockUsePathname.mockReturnValue("/dashboard");

    const { container } = render(<Sidebar profile={baseProfile} />);
    const dashboardLink = container.querySelector('a[href="/dashboard"]');
    expect(dashboardLink?.className).toContain("nav-item-active");

    // /watchlist link must NOT carry the active class.
    const watchlistLink = container.querySelector('a[href="/watchlist"]');
    expect(watchlistLink?.className).not.toContain("nav-item-active");
  });

  it("marks the dashboard link active when on a nested route like /dashboard/foo", () => {
    // pathname.startsWith(`${href}/`) is the second arm of the active
    // check; lock it in so a future refactor of NAV_ITEMS doesn't silently
    // break sub-route highlighting.
    mockUsePathname.mockReturnValue("/dashboard/something");

    const { container } = render(<Sidebar profile={baseProfile} />);
    const dashboardLink = container.querySelector('a[href="/dashboard"]');
    expect(dashboardLink?.className).toContain("nav-item-active");
  });

  it("renders without crashing when profile is null", () => {
    mockUsePathname.mockReturnValue("/dashboard");

    render(<Sidebar profile={null} />);

    // Admin link must stay hidden (null is not "admin").
    expect(screen.queryByRole("link", { name: /管理员/ })).not.toBeInTheDocument();
    // Primary nav must still render.
    expect(screen.getByRole("link", { name: /谐波分析/ })).toBeInTheDocument();
  });

  it("applies the optional className prop to the <aside>", () => {
    mockUsePathname.mockReturnValue("/dashboard");

    const { container } = render(
      <Sidebar profile={baseProfile} className="custom-extra-class" />
    );

    const aside = container.querySelector("aside");
    expect(aside?.className).toContain("custom-extra-class");
  });

  it("displays the brand label and Beta disclaimer", () => {
    mockUsePathname.mockReturnValue("/dashboard");

    render(<Sidebar profile={baseProfile} />);

    expect(screen.getByText("Pyharmonics")).toBeInTheDocument();
    expect(screen.getByText(/Beta 版本/)).toBeInTheDocument();
  });
});