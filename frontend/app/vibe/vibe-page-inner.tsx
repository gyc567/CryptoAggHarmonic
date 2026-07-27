"use client";

import { useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { useVibe } from "@/hooks/use-vibe";
import { VibeChat } from "@/components/vibe/vibe-chat";

export function VibePageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, loading: authLoading, getToken } = useAuth();
  const { messages, loading, error, sendMessage, stopRun } = useVibe({
    getToken,
    userId: user?.id,
  });
  const autoSent = useRef(false);

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace("/login");
    }
  }, [authLoading, user, router]);

  useEffect(() => {
    const prompt = searchParams.get("prompt");
    if (prompt && !autoSent.current && user) {
      autoSent.current = true;
      sendMessage(prompt);
      // Clean the query param without reloading.
      router.replace("/vibe", { scroll: false });
    }
  }, [searchParams, user, sendMessage, router]);

  if (authLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6">
      <div className="mx-auto max-w-4xl">
        <VibeChat
          messages={messages}
          loading={loading}
          error={error}
          onSend={sendMessage}
          onStop={stopRun}
        />
      </div>
    </div>
  );
}
