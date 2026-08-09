import { createBrowserClient } from "@supabase/ssr";
import type { AuthChangeEvent, Session } from "@supabase/supabase-js";

/**
 * Detect "unconfigured" Supabase env vars.
 *
 * The Supabase project URL always looks like `https://<id>.supabase.co`.
 * If we see the placeholder from `.env.example` or an empty value, the app
 * is NOT wired up to a real backend and must NOT silently fake a successful
 * login. The previous behavior auto-signed users in via a mock client that
 * bypassed auth entirely — a security footgun.
 */
const PLACEHOLDER_SUPABASE_URL = "https://your-project.supabase.co";

export function isSupabaseConfigured(): boolean {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return false;
  if (url === PLACEHOLDER_SUPABASE_URL) return false;
  if (key === "your-anon-key" || key.length < 20) return false;
  return true;
}

export function getMissingSupabaseEnvMessage(): string {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const missing: string[] = [];
  if (!url || url === PLACEHOLDER_SUPABASE_URL) missing.push("NEXT_PUBLIC_SUPABASE_URL");
  if (!key || key === "your-anon-key" || key.length < 20) missing.push("NEXT_PUBLIC_SUPABASE_ANON_KEY");
  return `Supabase 未配置：缺少 ${missing.join(", ")}。请在 frontend/.env 填写真实凭证后再启动。`;
}

export function createClient() {
  if (!isSupabaseConfigured()) {
    // Log once at module load so the cause is obvious in dev console.
    if (typeof window !== "undefined") {
      // eslint-disable-next-line no-console
      console.warn(getMissingSupabaseEnvMessage());
    }
    return createMisconfiguredClient();
  }
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );
}

/**
 * Returns a client that REFUSES to fake auth success. Every auth method
 * surfaces the configuration error to the caller so the UI can show it
 * instead of pretending to send a magic link.
 */

/** Error shape surfaced by the misconfigured client (mirrors AuthError). */
interface MisconfiguredAuthError {
  name: string;
  message: string;
  status: number;
}

/** Minimal auth surface the app consumes; keeps the mock typed without `any`. */
interface MisconfiguredSupabaseAuth {
  signInWithOtp: (options: {
    email: string;
    options?: { emailRedirectTo?: string };
  }) => Promise<{ data: { session: null; user: null }; error: MisconfiguredAuthError }>;
  signOut: () => Promise<{ error: null }>;
  getSession: () => Promise<{ data: { session: null }; error: null }>;
  getUser: () => Promise<{ data: { user: null }; error: null }>;
  onAuthStateChange: (
    callback: (event: AuthChangeEvent, session: Session | null) => void
  ) => { data: { subscription: { unsubscribe: () => void } } };
}

function createMisconfiguredClient(): { auth: MisconfiguredSupabaseAuth } {
  const message = getMissingSupabaseEnvMessage();
  const notConfigured = (): {
    data: { session: null; user: null };
    error: MisconfiguredAuthError;
  } => ({
    data: { session: null, user: null },
    error: { name: "SupabaseNotConfigured", message, status: 500 },
  });
  return {
    auth: {
      signInWithOtp: async () => notConfigured(),
      signOut: async () => ({ error: null }),
      getSession: async () => ({ data: { session: null }, error: null }),
      getUser: async () => ({ data: { user: null }, error: null }),
      onAuthStateChange: (callback) => {
        void callback;
        return { data: { subscription: { unsubscribe: () => {} } } };
      },
    },
  };
}