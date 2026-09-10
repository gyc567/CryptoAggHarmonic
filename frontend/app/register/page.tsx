"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Mail, Lock, Loader2, Gift, CheckCircle, AlertCircle } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";

function RegisterForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const inviteCode = searchParams.get("code");
  const { signUp } = useAuth();

  const [step, setStep] = useState<"form" | "email_sent">("form");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const validateForm = () => {
    const errors: Record<string, string> = {};
    if (!email || !email.includes("@")) {
      errors.email = "请输入有效的邮箱地址";
    }
    if (!password || password.length < 8) {
      errors.password = "密码至少 8 个字符";
    }
    if (password !== confirmPassword) {
      errors.confirmPassword = "两次输入的密码不一致";
    }
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!validateForm()) return;

    setLoading(true);

    try {
      const { error: signUpError } = await signUp(email, password, inviteCode);

      if (signUpError) {
        // Map Supabase errors to user-friendly messages
        const errorMessages: Record<string, string> = {
          "User already registered": "该邮箱已被注册，请直接登录",
          "Invalid email": "邮箱格式无效",
          "Password should be at least 6 characters": "密码至少 6 个字符",
          "Email rate limit exceeded": "请求过于频繁，请稍后再试",
          "Signup is disabled": "当前关闭注册，请联系管理员",
        };
        setError(errorMessages[signUpError.message] || signUpError.message);
        setLoading(false);
        return;
      }

      setStep("email_sent");
    } catch {
      setError("注册失败，请稍后重试");
      setLoading(false);
    }
  };

  if (step === "email_sent") {
    return (
      <div className="text-center space-y-4 py-8">
        <div className="mx-auto h-16 w-16 rounded-full bg-primary/10 flex items-center justify-center">
          <CheckCircle className="h-8 w-8 text-primary" />
        </div>
        <h2 className="text-xl font-semibold text-foreground">验证邮件已发送</h2>
        <p className="text-muted-foreground max-w-sm mx-auto">
          我们已发送验证链接到 <strong className="text-foreground">{email}</strong>
          <br />
          请点击邮件中的链接完成注册。
        </p>
        <button
          onClick={() => router.push("/login")}
          className="text-sm text-primary hover:underline"
        >
          返回登录
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {inviteCode && (
        <div className="p-3 bg-green-500/10 border border-green-500/30 rounded-lg flex items-center gap-2">
          <Gift className="h-4 w-4 text-green-500 shrink-0" />
          <span className="text-sm text-green-400">
            使用邀请码注册，将获得更高配额
          </span>
        </div>
      )}

      {error && (
        <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg flex items-start gap-2">
          <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
          <span className="text-sm text-red-400">{error}</span>
        </div>
      )}

      <div>
        <label htmlFor="email" className="block text-sm font-medium text-foreground mb-1.5">
          邮箱地址
        </label>
        <div className="relative">
          <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={cn(
              "w-full pl-10 p-2.5 border rounded-lg bg-background text-foreground placeholder:text-muted-foreground",
              fieldErrors.email ? "border-red-500" : "border-input"
            )}
            placeholder="you@example.com"
          />
        </div>
        {fieldErrors.email && (
          <p className="text-xs text-red-500 mt-1">{fieldErrors.email}</p>
        )}
      </div>

      <div>
        <label htmlFor="password" className="block text-sm font-medium text-foreground mb-1.5">
          密码
        </label>
        <div className="relative">
          <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            id="password"
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={cn(
              "w-full pl-10 p-2.5 border rounded-lg bg-background text-foreground placeholder:text-muted-foreground",
              fieldErrors.password ? "border-red-500" : "border-input"
            )}
            placeholder="至少 8 个字符"
          />
        </div>
        {fieldErrors.password && (
          <p className="text-xs text-red-500 mt-1">{fieldErrors.password}</p>
        )}
      </div>

      <div>
        <label htmlFor="confirmPassword" className="block text-sm font-medium text-foreground mb-1.5">
          确认密码
        </label>
        <div className="relative">
          <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            id="confirmPassword"
            type="password"
            required
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className={cn(
              "w-full pl-10 p-2.5 border rounded-lg bg-background text-foreground placeholder:text-muted-foreground",
              fieldErrors.confirmPassword ? "border-red-500" : "border-input"
            )}
            placeholder="再次输入密码"
          />
        </div>
        {fieldErrors.confirmPassword && (
          <p className="text-xs text-red-500 mt-1">{fieldErrors.confirmPassword}</p>
        )}
      </div>

      {inviteCode && (
        <input type="hidden" name="inviteCode" value={inviteCode} />
      )}

      <button
        type="submit"
        disabled={loading}
        className={cn(
          "w-full py-2.5 rounded-lg font-medium transition-colors flex items-center justify-center gap-2",
          loading
            ? "bg-muted text-muted-foreground cursor-not-allowed"
            : "bg-primary text-primary-foreground hover:bg-primary/90"
        )}
      >
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            注册中...
          </>
        ) : (
          "注册"
        )}
      </button>

      <p className="text-center text-sm text-muted-foreground">
        已有账号？{" "}
        <a href="/login" className="text-primary hover:underline">
          登录
        </a>
      </p>
    </form>
  );
}

export default function RegisterPage() {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-4">
      <div className="absolute inset-0 login-grid-line bg-login-grid opacity-40" />
      <div className="absolute inset-0 bg-gradient-to-b from-background via-transparent to-background" />

      <div className="relative z-10 w-full max-w-md">
        <div className="text-center mb-8">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-cy to-purple text-white shadow-glow-cyan mb-4">
            <svg
              className="h-6 w-6"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z"
              />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-gradient">创建账号</h1>
          <p className="text-muted-foreground mt-2">加入 CryptoAgg 开始交易</p>
        </div>

        <div className="glass-elevated p-6 sm:p-8">
          <Suspense
            fallback={
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            }
          >
            <RegisterForm />
          </Suspense>
        </div>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Beta 版本 · 仅供技术研究使用
        </p>
      </div>
    </div>
  );
}
