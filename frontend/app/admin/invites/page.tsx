"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { Loader2, Plus, Copy, Trash2, CheckCircle, XCircle, Gift } from "lucide-react";
import { cn } from "@/lib/utils";

interface Invite {
  id: string;
  email: string | null;
  code: string | null;
  status: string;
  quota: number;
  rsi_quota: number;
  used_count: number;
  max_uses: number;
  expires_at: string;
  created_at: string;
}

interface CreateInviteRequest {
  email?: string;
  quota: number;
  rsi_quota: number;
  max_uses: number;
  days_valid: number;
}

export default function AdminInvitesPage() {
  const router = useRouter();
  const { user, loading: authLoading, getToken } = useAuth();

  const [invites, setInvites] = useState<Invite[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [form, setForm] = useState<CreateInviteRequest>({
    email: "",
    quota: 5,
    rsi_quota: 50,
    max_uses: 1,
    days_valid: 7,
  });
  const [error, setError] = useState<string | null>(null);

  const isAdmin = user && (user as any).role === "admin";

  const fetchInvites = useCallback(async () => {
    const token = await getToken();
    if (!token) return;

    try {
      const res = await fetch("/api/admin/invites", {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.success) {
        setInvites(data.data.items);
      } else {
        setError(data.error?.message || "Failed to fetch invites");
      }
    } catch (err) {
      setError("Failed to fetch invites");
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace("/login");
    } else if (!authLoading && user && !isAdmin) {
      router.replace("/dashboard");
    } else if (user && isAdmin) {
      fetchInvites();
    }
  }, [authLoading, user, isAdmin, router, fetchInvites]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    setError(null);

    const token = await getToken();
    if (!token) return;

    try {
      const res = await fetch("/api/admin/invites", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (data.success) {
        setShowCreateForm(false);
        setForm({ email: "", quota: 5, rsi_quota: 50, max_uses: 1, days_valid: 7 });
        fetchInvites();
      } else {
        setError(data.error?.message || "Failed to create invite");
      }
    } catch {
      setError("Failed to create invite");
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (inviteId: string) => {
    if (!confirm("确定要撤销这个邀请码吗？")) return;

    const token = await getToken();
    if (!token) return;

    try {
      const res = await fetch(`/api/admin/invites/${inviteId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.success) {
        fetchInvites();
      } else {
        setError(data.error?.message || "Failed to revoke invite");
      }
    } catch {
      setError("Failed to revoke invite");
    }
  };

  const copyToClipboard = async (code: string, inviteId: string) => {
    await navigator.clipboard.writeText(code);
    setCopiedId(inviteId);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "pending":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-yellow-500/20 text-yellow-400">
            <CheckCircle className="h-3 w-3" /> 待使用
          </span>
        );
      case "accepted":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-green-500/20 text-green-400">
            <XCircle className="h-3 w-3" /> 已使用
          </span>
        );
      case "revoked":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-red-500/20 text-red-400">
            <XCircle className="h-3 w-3" /> 已撤销
          </span>
        );
      case "expired":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-gray-500/20 text-gray-400">
            <XCircle className="h-3 w-3" /> 已过期
          </span>
        );
      default:
        return (
          <span className="px-2 py-1 rounded-full text-xs bg-gray-500/20 text-gray-400">
            {status}
          </span>
        );
    }
  };

  if (authLoading || (!user && !loading)) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-foreground">邀请码管理</h1>
          <p className="text-muted-foreground mt-1">创建和管理邀请码</p>
        </div>
        <button
          onClick={() => setShowCreateForm(true)}
          className="btn-primary flex items-center gap-2"
        >
          <Plus className="h-4 w-4" />
          创建邀请码
        </button>
      </div>

      {error && (
        <div className="mb-6 p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400">
          {error}
        </div>
      )}

      {/* Create Form Modal */}
      {showCreateForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-xl border p-6 w-full max-w-md">
            <h2 className="text-lg font-semibold mb-4">创建邀请码</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">邮箱（可选）</label>
                <input
                  type="email"
                  value={form.email || ""}
                  onChange={(e) => setForm({ ...form, email: e.target.value || undefined })}
                  className="w-full p-2 border rounded-lg bg-background"
                  placeholder="留空则生成通用邀请码"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-1">日配额</label>
                  <input
                    type="number"
                    min={1}
                    max={1000}
                    value={form.quota}
                    onChange={(e) => setForm({ ...form, quota: parseInt(e.target.value) || 5 })}
                    className="w-full p-2 border rounded-lg bg-background"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">RSI配额</label>
                  <input
                    type="number"
                    min={1}
                    max={10000}
                    value={form.rsi_quota}
                    onChange={(e) => setForm({ ...form, rsi_quota: parseInt(e.target.value) || 50 })}
                    className="w-full p-2 border rounded-lg bg-background"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-1">可用次数</label>
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={form.max_uses}
                    onChange={(e) => setForm({ ...form, max_uses: parseInt(e.target.value) || 1 })}
                    className="w-full p-2 border rounded-lg bg-background"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">有效期（天）</label>
                  <input
                    type="number"
                    min={1}
                    max={365}
                    value={form.days_valid}
                    onChange={(e) => setForm({ ...form, days_valid: parseInt(e.target.value) || 7 })}
                    className="w-full p-2 border rounded-lg bg-background"
                  />
                </div>
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreateForm(false)}
                  className="flex-1 py-2 border rounded-lg hover:bg-muted transition-colors"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="flex-1 btn-primary flex items-center justify-center gap-2"
                >
                  {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                  创建
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Invites Table */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : (
        <div className="rounded-xl border bg-card overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="text-left p-4 font-medium">邀请码</th>
                <th className="text-left p-4 font-medium">邮箱</th>
                <th className="text-left p-4 font-medium">状态</th>
                <th className="text-left p-4 font-medium">配额</th>
                <th className="text-left p-4 font-medium">使用/最大</th>
                <th className="text-left p-4 font-medium">有效期</th>
                <th className="text-right p-4 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {invites.length === 0 ? (
                <tr>
                  <td colSpan={7} className="p-8 text-center text-muted-foreground">
                    暂无邀请码
                  </td>
                </tr>
              ) : (
                invites.map((invite) => (
                  <tr key={invite.id} className="border-b last:border-b-0 hover:bg-muted/30">
                    <td className="p-4">
                      <div className="flex items-center gap-2">
                        <code className="px-2 py-1 rounded bg-muted text-sm font-mono">
                          {invite.code || "-"}
                        </code>
                        {invite.code && (
                          <button
                            onClick={() => copyToClipboard(invite.code!, invite.id)}
                            className="p-1 hover:bg-muted rounded"
                            title="复制邀请码"
                          >
                            {copiedId === invite.id ? (
                              <CheckCircle className="h-4 w-4 text-green-500" />
                            ) : (
                              <Copy className="h-4 w-4 text-muted-foreground" />
                            )}
                          </button>
                        )}
                      </div>
                    </td>
                    <td className="p-4 text-sm">{invite.email || "-"}</td>
                    <td className="p-4">{getStatusBadge(invite.status)}</td>
                    <td className="p-4 text-sm">
                      <div className="flex items-center gap-1">
                        <Gift className="h-3 w-3 text-muted-foreground" />
                        {invite.quota}/{invite.rsi_quota}
                      </div>
                    </td>
                    <td className="p-4 text-sm">
                      {invite.used_count} / {invite.max_uses}
                    </td>
                    <td className="p-4 text-sm text-muted-foreground">
                      {new Date(invite.expires_at).toLocaleDateString("zh-CN")}
                    </td>
                    <td className="p-4 text-right">
                      {invite.status === "pending" && (
                        <button
                          onClick={() => handleRevoke(invite.id)}
                          className="p-2 hover:bg-red-500/10 rounded text-red-400"
                          title="撤销邀请码"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
