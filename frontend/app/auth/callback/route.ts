import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const ERROR_MESSAGES: Record<string, string> = {
  otp_expired: "登录链接已过期，请重新获取",
  invalid_token: "登录链接无效",
  rate_limit_exceeded: "请求过于频繁，请稍后再试",
  user_already_exists: "该邮箱已被注册",
  signup_disabled: "注册已关闭",
  unknown_error: "登录失败，请稍后重试",
};

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);

  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/dashboard";
  const error = searchParams.get("error");
  const errorDescription = searchParams.get("error_description");

  // Handle error cases with user-friendly messages
  if (error) {
    const message =
      ERROR_MESSAGES[error] ||
      errorDescription ||
      ERROR_MESSAGES.unknown_error;

    const redirectUrl = new URL(`${origin}/login`);
    redirectUrl.searchParams.set("error", message);
    return NextResponse.redirect(redirectUrl.toString());
  }

  // Validate code presence
  if (!code) {
    const redirectUrl = new URL(`${origin}/login`);
    redirectUrl.searchParams.set("error", "无效的登录链接");
    return NextResponse.redirect(redirectUrl.toString());
  }

  // Exchange code for session
  const supabase = createClient();
  const { error: sessionError } = await supabase.auth.exchangeCodeForSession(code);

  if (sessionError) {
    const redirectUrl = new URL(`${origin}/login`);
    redirectUrl.searchParams.set("error", sessionError.message);
    return NextResponse.redirect(redirectUrl.toString());
  }

  return NextResponse.redirect(`${origin}${next}`);
}
