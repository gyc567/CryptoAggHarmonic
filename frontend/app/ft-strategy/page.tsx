"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/use-auth";
import { StrategyCard } from "@/components/ft-strategy/StrategyCard";
import { listStrategies, deleteStrategy } from "@/lib/api-ft-strategy";
import type { FtStrategy } from "@/types/ft-strategy";

export default function FtStrategyListPage() {
  const { user, getToken } = useAuth();
  const [strategies, setStrategies] = useState<FtStrategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("all");

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const token = await getToken();
      if (!token) return;
      const data = await listStrategies(user.id, token, { limit: 50 });
      setStrategies(data);
    } catch (e) {
      console.error("Failed to load strategies:", e);
    } finally {
      setLoading(false);
    }
  }, [user, getToken]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll every 30s
  useEffect(() => {
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [load]);

  const handleDelete = async (id: string) => {
    if (!confirm("确定删除此策略？此操作不可撤销。")) return;
    try {
      const token = await getToken();
      if (!token) return;
      await deleteStrategy(id, token);
      setStrategies((prev) => prev.filter((s) => s.id !== id));
    } catch (e) {
      alert("删除失败：" + (e as Error).message);
    }
  };

  const filtered =
    filter === "all"
      ? strategies
      : strategies.filter((s) => s.status === filter);

  return (
    <div className="p-4 sm:p-6">
      <div className="mx-auto max-w-4xl">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-2xl font-bold text-white">FT 策略</h1>
          <Link
            href="/ft-strategy/new"
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500"
          >
            + 新建策略
          </Link>
        </div>

        <div className="mb-4 flex gap-2">
          {["all", "draft", "analyzed", "deployed", "rejected"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded px-3 py-1 text-xs transition-colors ${
                filter === f
                  ? "bg-blue-700 text-white"
                  : "bg-gray-800 text-gray-400 hover:bg-gray-700"
              }`}
            >
              {f === "all" ? "全部" : f.replace(/_/g, " ")}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="flex justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
          </div>
        ) : filtered.length === 0 ? (
          <div className="rounded border border-dashed border-gray-600 py-16 text-center text-gray-400">
            <p className="text-lg">暂无策略</p>
            <p className="mt-1 text-sm">点击上方「新建策略」开始</p>
          </div>
        ) : (
          <div className="space-y-3">
            {filtered.map((s) => (
              <StrategyCard
                key={s.id}
                strategy={s}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
