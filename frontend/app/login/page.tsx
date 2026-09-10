"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Mail, Lock, Loader2, Zap, AlertTriangle } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { isSupabaseConfigured, getMissingSupabaseEnvMessage } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

type LoginMode = "otp" | "password";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, loading: authLoading, signInWithOtp, signInWithPassword } = useAuth();
  const supabaseReady = useMemo(() => isSupabaseConfigured(), []);
  const configError = useMemo(
    () => (supabaseReady ? null : getMissingSupabaseEnvMessage()),
    [supabaseReady]
  );

  // Tab state
  const [mode, setMode] = useState<LoginMode>("otp");

  // Form state
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // UI state
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Read error from URL (e.g., from auth callback)
  const urlError = searchParams.get("error");

  useEffect(() => {
    if (urlError) {
      setError(decodeURIComponent(urlError));
    }
  }, [urlError]);

  useEffect(() => {
    if (user) {
      router.replace("/dashboard");
    }
  }, [user, router]);

  const handleOtpSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSending(true);

    const { error: authError } = await signInWithOtp(email.trim());

    setSending(false);
    if (authError) {
      setError(authError.message);
    } else {
      setSent(true);
    }
  };

  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSending(true);

    const { error: authError } = await signInWithPassword(email.trim(), password);

    setSending(false);
    if (authError) {
      setError(authError.message);
    } else {
      router.replace("/dashboard");
    }
  };

  const handleTabChange = (newMode: LoginMode) => {
    setMode(newMode);
    setError(null);
    setSent(false);
  };

  if (authLoading || user) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  // Email sent confirmation for OTP mode
  if (sent && mode === "otp") {
    return (
      <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-background px-4">
        <div className="absolute inset-0 login-grid-line bg-login-grid opacity-40" />
        <div className="absolute inset-0 bg-gradient-to-b from-background via-transparent to-background" />

        <div className="relative z-10 w-full max-w-md">
          <div className="glass-elevated p-8 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-success/10 text-success">
              <Mail className="h-6 w-6" />
            </div>
            <h2 className="mt-4 text-lg font-semibold text-foreground">
              魔法链接已发送
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              请检查邮箱 <strong className="text-foreground">{email}</strong>，点击链接登录
            </p>
            <button
              type="button"
              onClick={() => {
                setSent(false);
                setEmail("");
              }}
              className="mt-6 text-sm text-primary hover:underline"
            >
              使用其他邮箱
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-background px-4">
      <div className="absolute inset-0 login-grid-line bg-login-grid opacity-40" />
      <div className="absolute inset-0 bg-gradient-to-b from-background via-transparent to-background" />

      <div className="relative z-10 w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-cy to-purple text-white shadow-glow-cyan">
            <Zap className="h-7 w-7" />
          </div>
          <h1 className="mt-6 text-3xl font-bold text-gradient">CryptoAgg</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            谐波形态与背离分析
          </p>
        </div>

        <div className="glass-elevated p-6 sm:p-8">
          {configError && (
            <div
              role="alert"
              data-testid="supabase-config-error"
              className="mb-5 flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{configError}</span>
            </div>
          )}

          {error && (
            <div className="mb-5 flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Tab Switcher */}
          <div className="flex border-b border-border mb-6">
            <button
              type="button"
              onClick={() => handleTabChange("otp")}
              className={cn(
                "flex-1 py-2.5 text-sm font-medium transition-colors relative",
                mode === "otp"
                  ? "text-primary"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              魔法链接
              {mode === "otp" && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary" />
              )}
            </button>
            <button
              type="button"
              onClick={() => handleTabChange("password")}
              className={cn(
                "flex-1 py-2.5 text-sm font-medium transition-colors relative",
                mode === "password"
                  ? "text-primary"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              密码登录
              {mode === "password" && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary" />
              )}
            </button>
          </div>

          {/* OTP Login Form */}
          {mode === "otp" && (
            <form onSubmit={handleOtpSubmit} className="space-y-5">
              <div>
                <label
                  htmlFor="email"
                  className="block text-sm font-medium text-foreground mb-1.5"
                >
                  邮箱地址
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    id="email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="input-surface pl-10"
                    placeholder="you@example.com"
                  />
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  仅接受已邀请邮箱
                </p>
              </div>

              <button
                type="submit"
                disabled={sending || !email.trim() || !supabaseReady}
                className={cn(
                  "btn-primary w-full",
                  (sending || !email.trim() || !supabaseReady) && "opacity-60 cursor-not-allowed"
                )}
              >
                {sending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    发送中...
                  </>
                ) : (
                  "发送登录链接"
                )}
              </button>
            </form>
          )}

          {/* Password Login Form */}
          {mode === "password" && (
            <form onSubmit={handlePasswordSubmit} className="space-y-5">
              <div>
                <label
                  htmlFor="password-email"
                  className="block text-sm font-medium text-foreground mb-1.5"
                >
                  邮箱地址
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    id="password-email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="input-surface pl-10"
                    placeholder="you@example.com"
                  />
                </div>
              </div>

              <div>
                <label
                  htmlFor="password"
                  className="block text-sm font-medium text-foreground mb-1.5"
                >
                  密码
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    id="password"
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="input-surface pl-10"
                    placeholder="输入密码"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={sending || !email.trim() || !password || !supabaseReady}
                className={cn(
                  "btn-primary w-full",
                  (sending || !email.trim() || !password || !supabaseReady) && "opacity-60 cursor-not-allowed"
                )}
              >
                {sending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    登录中...
                  </>
                ) : (
                  "登录"
                )}
              </button>
            </form>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          没有账号？{" "}
          <a href="/register" className="text-primary hover:underline">
            注册
          </a>
        </p>

        <p className="mt-4 text-center text-xs text-muted-foreground">
          Beta 版本 · 仅供技术研究使用
        </p>
      </div>
    </div>
  );
}
