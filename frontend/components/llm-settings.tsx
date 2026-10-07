'use client';

import { useEffect, useState } from 'react';
import { Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react';

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
import {
  type LlmProfileInput,
  type LlmProfiles,
  fetchVendorModels,
  getLlmProfiles,
  saveLlmSettings,
} from '@/lib/api';

type VendorPreset = {
  vendor: string;
  base_url: string;
  models: string[];
};

// 常见厂家的 OpenAI 兼容入口与常用模型；「自定义」则完全手填
const VENDOR_PRESETS: VendorPreset[] = [
  {
    vendor: '智谱',
    base_url: 'https://open.bigmodel.cn/api/paas/v4/',
    models: ['glm-5.3-flash', 'glm-5.3', 'glm-4.6', 'glm-4.5-air'],
  },
  {
    vendor: 'DeepSeek',
    base_url: 'https://api.deepseek.com',
    models: ['deepseek-chat', 'deepseek-reasoner'],
  },
  {
    vendor: '通义千问',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: ['qwen-max', 'qwen-plus', 'qwen-flash', 'qwen-turbo'],
  },
  {
    vendor: '自定义',
    base_url: '',
    models: [],
  },
];

type Draft = LlmProfileInput & { key_hint: string };

type FormState = {
  vendor: string;
  name: string;
  model: string;
  base_url: string;
  api_key: string;
};

const EMPTY_FORM: FormState = {
  vendor: VENDOR_PRESETS[0].vendor,
  name: '',
  model: '',
  base_url: VENDOR_PRESETS[0].base_url,
  api_key: '',
};

export function LlmSettingsDialog({
  open,
  onOpenChange,
  token,
  llm,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  token: string;
  llm: LlmProfiles | null;
  onSaved: (profiles: LlmProfiles) => void;
}) {
  const [drafts, setDrafts] = useState<Draft[]>(() =>
    (llm?.profiles ?? []).map((profile) => ({ ...profile, api_key: '' })),
  );
  const [editing, setEditing] = useState<number | 'new' | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [fetchedModels, setFetchedModels] = useState<string[]>([]);
  const [fetching, setFetching] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    void getLlmProfiles(token, controller.signal)
      .then((profiles) => {
        if (cancelled) return;
        setDrafts(
          profiles.profiles.map((profile) => ({ ...profile, api_key: '' })),
        );
        onSaved(profiles);
      })
      .catch((loadError: unknown) => {
        if (cancelled) return;
        setLoadError(
          controller.signal.aborted
            ? '加载超时，请检查后端连接后重新打开设置'
            : loadError instanceof Error
              ? loadError.message
              : '加载供应商配置失败',
        );
      })
      .finally(() => {
        window.clearTimeout(timeout);
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [open, token, onSaved]);

  function applyPreset(vendor: string) {
    const preset =
      VENDOR_PRESETS.find((item) => item.vendor === vendor) ??
      VENDOR_PRESETS[0];
    setFetchedModels([]);
    setForm((current) => ({
      ...current,
      vendor,
      base_url: preset.base_url,
      model: preset.models[0] ?? '',
      name:
        !current.name ||
        VENDOR_PRESETS.some((item) => item.vendor === current.name)
          ? vendor
          : current.name,
    }));
  }

  function startAdd() {
    setForm(EMPTY_FORM);
    setFetchedModels([]);
    setEditing('new');
  }

  function startEdit(index: number) {
    const draft = drafts[index];
    setForm({
      vendor: '自定义',
      name: draft.name,
      model: draft.model,
      base_url: draft.base_url,
      api_key: '',
    });
    setFetchedModels([]);
    setEditing(index);
  }

  // 用刚填的 key 去厂家拉取真实可用模型列表，拉到后模型字段变下拉选择
  async function handleFetchModels() {
    if (!form.base_url.trim()) {
      setError('先填写接口地址');
      return;
    }
    if (!form.api_key.trim()) {
      setError('先填写 API Key 才能查询该厂家的模型列表');
      return;
    }
    setFetching(true);
    setError('');
    try {
      const models = await fetchVendorModels(
        token,
        form.base_url,
        form.api_key,
      );
      setFetchedModels(models);
      if (models.length === 0) {
        setError('厂家返回了空的模型列表，请手动输入模型名');
      } else if (!models.includes(form.model.trim())) {
        setForm((current) => ({ ...current, model: models[0] }));
      }
    } catch (fetchError) {
      setFetchedModels([]);
      setError(
        fetchError instanceof Error ? fetchError.message : '查询模型列表失败',
      );
    } finally {
      setFetching(false);
    }
  }

  function submitForm() {
    const trimmed = {
      name: form.name.trim(),
      model: form.model.trim(),
      base_url: form.base_url.trim(),
      api_key: form.api_key.trim(),
    };
    if (!trimmed.name || !trimmed.model || !trimmed.base_url) {
      setError('名称、模型和接口地址都是必填项');
      return;
    }
    if (editing === 'new' && !trimmed.api_key) {
      setError('新档案需要填写 API Key');
      return;
    }
    setDrafts((current) => {
      if (editing === 'new') {
        return [...current, { ...trimmed, key_hint: '' }];
      }
      if (editing === null) return current;
      const next = [...current];
      const existing = next[editing];
      next[editing] = {
        ...trimmed,
        // 留空表示沿用已存储的 key
        api_key: trimmed.api_key || existing.api_key,
        key_hint: trimmed.api_key
          ? `${trimmed.api_key.slice(0, 4)}****`
          : existing.key_hint,
      };
      return next;
    });
    setError('');
    setEditing(null);
  }

  function removeDraft(index: number) {
    setDrafts((current) => current.filter((_, i) => i !== index));
    if (editing === index) setEditing(null);
  }

  async function handleSave() {
    if (drafts.length === 0) {
      setError('至少需要保留一个供应商档案');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const result = await saveLlmSettings(
        token,
        drafts.map(({ name, model, base_url, api_key }) => ({
          name,
          model,
          base_url,
          api_key,
        })),
      );
      onSaved(result);
      onOpenChange(false);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>模型供应商设置</DialogTitle>
          <DialogDescription>
            配置常见厂家的 API；保存后立即生效，密钥只保存在服务端。
          </DialogDescription>
        </DialogHeader>

        {loading && (
          <output className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
            <RefreshCw className="size-4 animate-spin" /> 正在加载供应商配置…
          </output>
        )}
        {loadError && (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-600"
          >
            加载供应商配置失败：{loadError}
          </div>
        )}
        <div hidden={loading || Boolean(loadError)} className="space-y-4">
          <div className="space-y-2">
            {drafts.map((draft, index) => (
              <div
                key={draft.name}
                className="flex items-center gap-3 rounded-lg border border-border px-3 py-2.5"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-foreground">
                    {draft.name}
                    {llm?.active === draft.name && (
                      <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
                        当前
                      </span>
                    )}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {draft.model}
                    {draft.key_hint && ` · Key ${draft.key_hint}`}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`编辑 ${draft.name}`}
                  onClick={() => startEdit(index)}
                >
                  <Pencil />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`删除 ${draft.name}`}
                  disabled={drafts.length === 1}
                  onClick={() => removeDraft(index)}
                >
                  <Trash2 />
                </Button>
              </div>
            ))}

            {editing === null && (
              <Button
                variant="outline"
                className="w-full justify-start"
                onClick={startAdd}
              >
                <Plus /> 添加供应商
              </Button>
            )}
          </div>

          {editing !== null && (
            <div className="space-y-4 rounded-lg border border-border p-4">
              <div className="space-y-2">
                <Label htmlFor="llm-vendor">厂家</Label>
                <select
                  id="llm-vendor"
                  value={form.vendor}
                  onChange={(event) => applyPreset(event.target.value)}
                  className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {VENDOR_PRESETS.map((preset) => (
                    <option key={preset.vendor} value={preset.vendor}>
                      {preset.vendor}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="llm-name">显示名称</Label>
                <Input
                  id="llm-name"
                  value={form.name}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      name: event.target.value,
                    }))
                  }
                  placeholder="例如：智谱"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="llm-model">
                  模型
                  {fetchedModels.length > 0 && (
                    <span className="ml-2 text-[11px] font-normal text-muted-foreground">
                      （该 Key 可用 {fetchedModels.length} 个，下拉选择）
                    </span>
                  )}
                </Label>
                {fetchedModels.length > 0 ? (
                  <select
                    id="llm-model"
                    value={form.model}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        model: event.target.value,
                      }))
                    }
                    className="h-10 w-full rounded-lg border border-border bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {!fetchedModels.includes(form.model) && form.model && (
                      <option value={form.model}>{form.model}（当前）</option>
                    )}
                    {fetchedModels.map((model) => (
                      <option key={model} value={model}>
                        {model}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Input
                    id="llm-model"
                    list="llm-model-suggestions"
                    value={form.model}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        model: event.target.value,
                      }))
                    }
                    placeholder="例如：glm-5.3-flash；填好 Key 后可点右侧按钮获取"
                  />
                )}
                {!fetchedModels.length && (
                  <datalist id="llm-model-suggestions">
                    {(
                      VENDOR_PRESETS.find((item) => item.vendor === form.vendor)
                        ?.models ?? []
                    ).map((model) => (
                      <option key={model} value={model}>
                        {model}
                      </option>
                    ))}
                  </datalist>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="w-full"
                  disabled={fetching}
                  onClick={() => void handleFetchModels()}
                >
                  {fetching ? (
                    <RefreshCw className="animate-spin" />
                  ) : (
                    <RefreshCw />
                  )}
                  {fetching ? '正在查询…' : '获取该 Key 可用的模型列表'}
                </Button>
              </div>

              <div className="space-y-2">
                <Label htmlFor="llm-base-url">接口地址（OpenAI 兼容）</Label>
                <Input
                  id="llm-base-url"
                  value={form.base_url}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      base_url: event.target.value,
                    }))
                  }
                  placeholder="https://…/v1"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="llm-api-key">API Key</Label>
                <Input
                  id="llm-api-key"
                  type="password"
                  value={form.api_key}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      api_key: event.target.value,
                    }))
                  }
                  placeholder={
                    editing === 'new'
                      ? '填写厂家提供的 API Key'
                      : `已配置${drafts[editing]?.key_hint ?? ''}，留空保持不变`
                  }
                />
              </div>

              <div className="flex gap-2">
                <Button onClick={submitForm}>确认该档案</Button>
                <Button variant="ghost" onClick={() => setEditing(null)}>
                  取消
                </Button>
              </div>
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
        </div>

        <DialogFooter>
          <Button
            onClick={() => void handleSave()}
            disabled={saving || loading || Boolean(loadError)}
          >
            {saving ? '正在保存…' : '保存并应用'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
