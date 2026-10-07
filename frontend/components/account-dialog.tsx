'use client';

import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { type UserProfile, getCurrentUser, updateProfile } from '@/lib/api';

export function AccountDialog({
  open,
  onOpenChange,
  token,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  token: string;
  onSaved: (user: UserProfile) => void;
}) {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [createdAt, setCreatedAt] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // 打开时从后端拉最新资料，避免用到 localStorage 里的旧值
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    getCurrentUser(token)
      .then((user) => {
        if (cancelled) return;
        setUsername(user.username ?? '');
        setEmail(user.email);
        setCreatedAt(user.created_at ?? '');
      })
      .catch((loadError) => {
        if (!cancelled)
          setError(
            loadError instanceof Error ? loadError.message : '加载账号信息失败',
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, token]);

  async function handleSave() {
    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      setError('邮箱不能为空');
      return;
    }
    setSaving(true);
    setError('');
    try {
      // 空字符串表示清空显示名称（后端语义如此）
      const updated = await updateProfile(token, {
        username: username.trim(),
        email: trimmedEmail,
      });
      onSaved({
        id: updated.id,
        email: updated.email,
        username: updated.username,
      });
      onOpenChange(false);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>账号管理</DialogTitle>
          <DialogDescription>
            修改显示名称或邮箱，保存后立即生效。
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
            <RefreshCw className="size-4 animate-spin" />
            正在加载…
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="account-username">显示名称</Label>
              <Input
                id="account-username"
                value={username}
                maxLength={50}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="留空则不显示名称"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="account-email">邮箱</Label>
              <Input
                id="account-email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            {createdAt && (
              <p className="text-xs text-muted-foreground">
                注册时间：{new Date(createdAt).toLocaleString('zh-CN')}
              </p>
            )}
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-600"
          >
            {error}
          </div>
        )}

        <DialogFooter>
          <Button
            onClick={() => void handleSave()}
            disabled={loading || saving}
          >
            {saving ? '正在保存…' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
