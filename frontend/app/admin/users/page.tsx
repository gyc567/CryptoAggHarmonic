"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { Loader2, Search, ChevronLeft, ChevronRight, Shield, UserX } from "lucide-react";
import { cn } from "@/lib/utils";

interface User {
  id: string;
  email: string;
  role: string;
  status: string;
  daily_quota: number;
  rsi_daily_quota: number;
  created_at: string;
  total_analyses: number;
  invited_by: string | null;
}

export default function AdminUsersPage() {
  const router = useRouter();
  const { user, loading: authLoading, getToken } = useAuth();

  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [limit] = useState(20);
  const [search, setSearch] = useState("");
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isAdmin = user && (user as any).role === "admin";

  const fetchUsers = useCallback(async () => {
    const token = await getToken();
    if (!token) return;

    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), limit: String(limit) });
      if (search) params.set("search", search);

      const res = await fetch(`/api/admin/users?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.success) {
        setUsers(data.data.items);
        setTotal(data.data.total);
      } else {
        setError(data.error?.message || "Failed to fetch users");
      }
    } catch {
      setError("Failed to fetch users");
    } finally {
      setLoading(false);
    }
  }, [getToken, page, limit, search]);

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace("/login");
    } else if (!authLoading && user && !isAdmin) {
      router.replace("/dashboard");
    } else if (user && isAdmin) {
      fetchUsers();
    }
  }, [authLoading, user, isAdmin, router, fetchUsers]);

  const handleUpdateUser = async (userId: string, updates: Record<string, any>) => {
    const token = await getToken();
    if (!token) return;

    try {
      const res = await fetch(`/api/admin/users/${userId}`, {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(updates),
      });
      const data = await res.json();
      if (data.success) {
        setEditingUser(null);
        fetchUsers();
      } else {
        setError(data.error?.message || "Failed to update user");
      }
    } catch {
      setError("Failed to update user");
    }
  };

  const totalPages = Math.ceil(total / limit);

  const getRoleBadge = (role: string) => {
    switch (role) {
      case "admin":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-purple-500/20 text-purple-400">
            <Shield className="h-3 w-3" /> 管理员
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-blue-500/20 text-blue-400">
            用户
          </span>
        );
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "active":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-green-500/20 text-green-400">
            正常
          </span>
        );
      case "suspended":
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-red-500/20 text-red-400">
            <UserX className="h-3 w-3" /> 停用
          </span>
        );
      default:
        return <span className="text-sm text-muted-foreground">{status}</span>;
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
          <h1 className="text-2xl font-bold text-foreground">用户管理</h1>
          <p className="text-muted-foreground mt-1">
            共 {total} 位用户，第 {page} / {totalPages} 页
          </p>
        </div>
      </div>

      {error && (
        <div className="mb-6 p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400">
          {error}
        </div>
      )}

      {/* Search */}
      <div className="relative mb-6">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <input
          type="text"
          placeholder="搜索邮箱..."
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          className="w-full max-w-sm pl-10 pr-4 py-2 border rounded-lg bg-background"
        />
      </div>

      {/* Edit Modal */}
      {editingUser && (
        <EditUserModal
          user={editingUser}
          onSave={(updates) => handleUpdateUser(editingUser.id, updates)}
          onClose={() => setEditingUser(null)}
        />
      )}

      {/* Users Table */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      ) : (
        <>
          <div className="rounded-xl border bg-card overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="text-left p-4 font-medium">用户</th>
                  <th className="text-left p-4 font-medium">角色</th>
                  <th className="text-left p-4 font-medium">状态</th>
                  <th className="text-left p-4 font-medium">日配额</th>
                  <th className="text-left p-4 font-medium">RSI配额</th>
                  <th className="text-left p-4 font-medium">分析次数</th>
                  <th className="text-left p-4 font-medium">注册时间</th>
                  <th className="text-right p-4 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {users.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="p-8 text-center text-muted-foreground">
                      暂无用户
                    </td>
                  </tr>
                ) : (
                  users.map((u) => (
                    <tr key={u.id} className="border-b last:border-b-0 hover:bg-muted/30">
                      <td className="p-4">
                        <div className="text-sm font-medium">{u.email}</div>
                        <div className="text-xs text-muted-foreground font-mono">{u.id.slice(0, 8)}...</div>
                      </td>
                      <td className="p-4">{getRoleBadge(u.role)}</td>
                      <td className="p-4">{getStatusBadge(u.status)}</td>
                      <td className="p-4 text-sm">{u.daily_quota}</td>
                      <td className="p-4 text-sm">{u.rsi_daily_quota}</td>
                      <td className="p-4 text-sm">{u.total_analyses}</td>
                      <td className="p-4 text-sm text-muted-foreground">
                        {new Date(u.created_at).toLocaleDateString("zh-CN")}
                      </td>
                      <td className="p-4 text-right">
                        <button
                          onClick={() => setEditingUser(u)}
                          className="px-3 py-1 text-sm border rounded hover:bg-muted transition-colors"
                        >
                          编辑
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 mt-6">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="p-2 border rounded hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="text-sm text-muted-foreground">
                第 {page} / {totalPages} 页
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="p-2 border rounded hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

interface EditUserModalProps {
  user: User;
  onSave: (updates: Record<string, any>) => void;
  onClose: () => void;
}

function EditUserModal({ user, onSave, onClose }: EditUserModalProps) {
  const [form, setForm] = useState({
    daily_quota: user.daily_quota,
    rsi_daily_quota: user.rsi_daily_quota,
    status: user.status,
    role: user.role,
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const updates: Record<string, any> = {};
    if (form.daily_quota !== user.daily_quota) updates.daily_quota = form.daily_quota;
    if (form.rsi_daily_quota !== user.rsi_daily_quota) updates.rsi_daily_quota = form.rsi_daily_quota;
    if (form.status !== user.status) updates.status = form.status;
    if (form.role !== user.role) updates.role = form.role;
    if (Object.keys(updates).length > 0) {
      onSave(updates);
    } else {
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-card rounded-xl border p-6 w-full max-w-md">
        <h2 className="text-lg font-semibold mb-4">编辑用户</h2>
        <p className="text-sm text-muted-foreground mb-4">{user.email}</p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">日配额</label>
              <input
                type="number"
                min={1}
                max={10000}
                value={form.daily_quota}
                onChange={(e) => setForm({ ...form, daily_quota: parseInt(e.target.value) || 1 })}
                className="w-full p-2 border rounded-lg bg-background"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">RSI配额</label>
              <input
                type="number"
                min={1}
                max={100000}
                value={form.rsi_daily_quota}
                onChange={(e) => setForm({ ...form, rsi_daily_quota: parseInt(e.target.value) || 1 })}
                className="w-full p-2 border rounded-lg bg-background"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1">状态</label>
              <select
                value={form.status}
                onChange={(e) => setForm({ ...form, status: e.target.value })}
                className="w-full p-2 border rounded-lg bg-background"
              >
                <option value="active">正常</option>
                <option value="suspended">停用</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">角色</label>
              <select
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
                className="w-full p-2 border rounded-lg bg-background"
              >
                <option value="user">用户</option>
                <option value="admin">管理员</option>
              </select>
            </div>
          </div>
          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2 border rounded-lg hover:bg-muted transition-colors"
            >
              取消
            </button>
            <button type="submit" className="flex-1 btn-primary">
              保存
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
