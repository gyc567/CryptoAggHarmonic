"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Mail, Loader2, Zap, AlertTriangle } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { isSupabaseConfigured, getMissingSupabaseEnvMessage } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading: authLoading, signInWithOtp } = useAuth();
  const supabaseReady = useMemo(() => isSupabaseConfigured(), []);
  const configError = useMemo(
    () => (supabaseReady ? null : getMissingSupabaseEnvMessage()),
    [supabaseReady]
  );
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user) {
      router.replace("/dashboard");
    }
  }, [user, router]);

  const handleSubmit = async (e: React.FormEvent) => {
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

  if (authLoading || user) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent" />
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
          <h1 className="mt-6 text-3xl font-bold text-gradient">
            Pyharmonics
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            邀请制谐波形态与背离分析
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
          {sent ? (
            <div className="text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-success/10 text-success">
                <Mail className="h-6 w-6" />
              </div>
              <h2 className="mt-4 text-lg font-semibold text-foreground">
                魔法链接已发送
              </h2>
              <p className="mt-2 text-sm text-muted-foreground">
                请检查邮箱 {email}，点击链接登录
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
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label
                  htmlFor="email"
                  className="block text-sm font-medium text-foreground"
                >
                  邮箱地址
                </label>
                <div className="relative mt-1.5">
                  <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    id="email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="input-surface pl-10"
                  />
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  仅接受已邀请邮箱
                </p>
              </div>

              {error && (
                <div className="rounded-lg border border-danger/20 bg-danger/10 px-3 py-2 text-sm text-danger">
                  {error}
                </div>
              )}

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
                  "发送魔法链接"
                )}
              </button>
            </form>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Beta 版本 · 仅供技术研究使用
        </p>
      </div>
    </div>
  );
}
