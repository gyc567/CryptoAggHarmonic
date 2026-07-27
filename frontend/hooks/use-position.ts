"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { positionDb } from "@/lib/position/db";
import {
  computeBuckets,
  computeDiagnostics,
  computeRiskLevel,
  computeValidation,
  simulateWhatIf,
} from "@/lib/position/calculator";
import { createDefaultBalance, DEFAULT_CHECKLIST, DEFAULT_CONFIG } from "@/lib/position/defaults";
import type {
  AccountBucket,
  ColdCheckItem,
  DiagnosticItem,
  LongTermHolding,
  PositionBalance,
  PositionConfig,
  RiskLevel,
  ValidationResult,
  WhatIfResult,
} from "@/types/position";

interface UsePositionOptions {
  userId?: string;
  initialPlannedTrade?: number;
}

export function usePosition({ userId, initialPlannedTrade = 0.5 }: UsePositionOptions) {
  const [config, setConfig] = useState<PositionConfig | null>(null);
  const [balance, setBalance] = useState<PositionBalance | null>(null);
  const [plannedTrade, setPlannedTrade] = useState(initialPlannedTrade);
  const [actualTrade, setActualTrade] = useState(initialPlannedTrade);
  const [checklist, setChecklist] = useState<ColdCheckItem[]>(DEFAULT_CHECKLIST);
  const [holdings, setHoldings] = useState<LongTermHolding[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Load persisted config and balance
  useEffect(() => {
    if (!userId) {
      setConfig(DEFAULT_CONFIG);
      setBalance(createDefaultBalance(DEFAULT_CONFIG));
      setLoading(false);
      return;
    }

    let mounted = true;
    setLoading(true);

    Promise.all([positionDb.loadConfig(userId), positionDb.loadBalance(userId)])
      .then(([savedConfig, savedBalance]) => {
        /* istanbul ignore next -- cleanup guard */
        if (!mounted) return;
        const nextConfig = savedConfig ?? DEFAULT_CONFIG;
        const nextBalance = savedBalance ?? createDefaultBalance(nextConfig);
        setConfig(nextConfig);
        setBalance(nextBalance);
      })
      .finally(() => {
        /* istanbul ignore next -- cleanup guard */
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [userId]);

  // Load holdings
  useEffect(() => {
    if (!userId) {
      setHoldings([]);
      return;
    }
    let mounted = true;
    Promise.resolve(positionDb.listHoldings(userId)).then((data) => {
      /* istanbul ignore next -- cleanup guard */
      if (mounted) setHoldings(data ?? []);
    });
    return () => {
      mounted = false;
    };
  }, [userId]);

  const buckets = useMemo<AccountBucket[]>(() => {
    if (!config || !balance) return [];
    return computeBuckets(config, balance);
  }, [config, balance]);

  const riskLevel = useMemo<RiskLevel>(() => {
    if (!config || !balance) {
      return {
        level: 0,
        label: "0 级",
        minWu: 0,
        maxWu: 0,
        trouble: "无额外麻烦",
        cooldown: "至少确认逻辑",
      };
    }
    return computeRiskLevel(config, balance, plannedTrade);
  }, [config, balance, plannedTrade]);

  const validation = useMemo<ValidationResult[]>(() => {
    if (!config || !balance) return [];
    return computeValidation(config);
  }, [config, balance]);

  const diagnostics = useMemo<DiagnosticItem[]>(() => {
    if (!config) return [];
    return computeDiagnostics(config);
  }, [config]);

  const whatIf = useMemo<WhatIfResult>(() => {
    if (!config || !balance) {
      return {
        tradeWu: 0,
        consumedEmergencyWu: 0,
        consumedBtcWu: 0,
        consumedMidWu: 0,
        consumedSmallTradableWu: 0,
        consumedSmallReserveWu: 0,
        remainingEmergencyWu: 0,
        remainingBtcWu: 0,
        remainingMidWu: 0,
        remainingSmallTradableWu: 0,
        remainingSmallReserveWu: 0,
        remainingTotalWu: 0,
        touchesEmergency: false,
      };
    }
    return simulateWhatIf(config, balance, actualTrade);
  }, [config, balance, actualTrade]);

  // Recompute balance and persist whenever config changes. Keeping side effects
  // out of the state updater makes the hook concurrent-safe and easier to test.
  useEffect(() => {
    if (!config) return;
    const nextBalance = createDefaultBalance(config);
    setBalance(nextBalance);
    if (!userId) return;

    setSaving(true);
    Promise.all([
      positionDb.saveConfig(userId, config),
      positionDb.saveBalance(userId, nextBalance),
    ]).finally(() => setSaving(false));
  }, [config, userId]);

  const updateConfig = useCallback(
    async (updater: (prev: PositionConfig) => PositionConfig) => {
      setConfig((prev) => {
        if (!prev) return prev;
        return updater(prev);
      });
    },
    []
  );

  const updateBalance = useCallback(
    async (nextBalance: PositionBalance) => {
      setBalance(nextBalance);
      if (userId) {
        setSaving(true);
        await positionDb.saveBalance(userId, nextBalance);
        setSaving(false);
      }
    },
    [userId]
  );

  const toggleChecklist = useCallback((id: string) => {
    setChecklist((prev) =>
      prev.map((item) => (item.id === id ? { ...item, checked: !item.checked } : item))
    );
  }, []);

  const allChecked = useMemo(() => checklist.every((item) => item.checked), [checklist]);

  const archiveWhatIf = useCallback(async () => {
    if (!config || !balance || whatIf.touchesEmergency) return;
    const nextBalance: PositionBalance = {
      emergencyWu: whatIf.remainingEmergencyWu,
      btcWu: whatIf.remainingBtcWu,
      midWu: whatIf.remainingMidWu,
      smallTradableWu: whatIf.remainingSmallTradableWu,
      smallReserveWu: whatIf.remainingSmallReserveWu,
      cutPositionWu: balance.cutPositionWu,
    };
    await updateBalance(nextBalance);
  }, [config, balance, whatIf, updateBalance]);

  const addHolding = useCallback(
    async (holding: Omit<LongTermHolding, "id" | "createdAt">) => {
      if (!userId) return;
      const created = await positionDb.createHolding(userId, holding);
      setHoldings((prev) => [created, ...prev]);
      return created;
    },
    [userId]
  );

  const updateHolding = useCallback(
    async (id: string, patch: Partial<Omit<LongTermHolding, "id" | "createdAt">>) => {
      if (!userId) return;
      const updated = await positionDb.updateHolding(userId, id, patch);
      setHoldings((prev) => prev.map((h) => (h.id === id ? updated : h)));
      return updated;
    },
    [userId]
  );

  const deleteHolding = useCallback(
    async (id: string) => {
      if (!userId) return;
      await positionDb.deleteHolding(userId, id);
      setHoldings((prev) => prev.filter((h) => h.id !== id));
    },
    [userId]
  );

  return {
    config,
    balance,
    buckets,
    plannedTrade,
    actualTrade,
    checklist,
    allChecked,
    riskLevel,
    validation,
    diagnostics,
    whatIf,
    holdings,
    loading,
    saving,
    setPlannedTrade,
    setActualTrade,
    updateConfig,
    updateBalance,
    toggleChecklist,
    archiveWhatIf,
    addHolding,
    updateHolding,
    deleteHolding,
  };
}
