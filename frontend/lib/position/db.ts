/**
 * localStorage-backed persistence for the position feature.
 *
 * The page tests (`app/position/page.test.tsx`, `hooks/use-position.test.tsx`)
 * mock this module entirely, so the real implementation only needs to behave
 * plausibly for the dev browser. Keyed by userId so multi-account switches
 * don't leak state.
 *
 * Replace with the backend persistence layer once `/api/position/...` ships.
 */
import type {
  LongTermHolding,
  PositionBalance,
  PositionConfig,
} from "@/types/position";

const k = (userId: string, suffix: string): string => `position:${userId}:${suffix}`;

function readJson<T>(key: string): T | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(key);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function writeJson(key: string, value: unknown): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(key, JSON.stringify(value));
}

function newId(): string {
  return `h_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export const positionDb = {
  async loadConfig(userId: string): Promise<PositionConfig | null> {
    return readJson<PositionConfig>(k(userId, "config"));
  },

  async saveConfig(userId: string, config: PositionConfig): Promise<void> {
    writeJson(k(userId, "config"), config);
  },

  async loadBalance(userId: string): Promise<PositionBalance | null> {
    return readJson<PositionBalance>(k(userId, "balance"));
  },

  async saveBalance(userId: string, balance: PositionBalance): Promise<void> {
    writeJson(k(userId, "balance"), balance);
  },

  async listHoldings(userId: string): Promise<LongTermHolding[]> {
    return readJson<LongTermHolding[]>(k(userId, "holdings")) ?? [];
  },

  async createHolding(
    userId: string,
    holding: Omit<LongTermHolding, "id" | "createdAt">,
  ): Promise<LongTermHolding> {
    const list = await positionDb.listHoldings(userId);
    const created: LongTermHolding = {
      ...holding,
      id: newId(),
      createdAt: new Date().toISOString(),
    };
    list.unshift(created);
    writeJson(k(userId, "holdings"), list);
    return created;
  },

  async updateHolding(
    userId: string,
    id: string,
    patch: Partial<Omit<LongTermHolding, "id" | "createdAt">>,
  ): Promise<LongTermHolding> {
    const list = await positionDb.listHoldings(userId);
    const idx = list.findIndex((h) => h.id === id);
    if (idx < 0) throw new Error(`Holding ${id} not found`);
    const updated: LongTermHolding = { ...list[idx], ...patch };
    list[idx] = updated;
    writeJson(k(userId, "holdings"), list);
    return updated;
  },

  async deleteHolding(userId: string, id: string): Promise<void> {
    const list = await positionDb.listHoldings(userId);
    const filtered = list.filter((h) => h.id !== id);
    writeJson(k(userId, "holdings"), filtered);
  },

  // No-op for now; the page test calls it but a real impl would post to /api/position/readiness.
  async logTradeReadiness(
    userId: string,
    payload: Omit<import("@/types/position").TradeReadinessLog, "id" | "userId">,
  ): Promise<void> {
    if (typeof window === "undefined") return;
    void userId;
    void payload;
  },
};

export type PositionDb = typeof positionDb;