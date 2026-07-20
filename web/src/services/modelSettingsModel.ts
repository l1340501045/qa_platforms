import type {
  AIModelKeyStatus,
  AIModelRole,
  AIModelSetting,
  AIModelSettings,
  ModelConnectionRequest,
} from '../types';

export interface ModelFormValues {
  base_url: string;
  model_name: string;
  api_key: string;
}

export const MODEL_ROLE_ORDER: readonly AIModelRole[] = [
  'primary',
  'vision',
  'verify',
  'embedding',
];

export class IncompleteModelSettingsError extends Error {
  constructor(detail: string) {
    super(`模型配置不完整：${detail}。请刷新重试或联系平台维护人员。`);
    this.name = 'IncompleteModelSettingsError';
  }
}

function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, '');
}

export function sortModelSettings<T extends { role: AIModelRole }>(models: T[]): T[] {
  const position = new Map(MODEL_ROLE_ORDER.map((role, index) => [role, index]));
  return [...models].sort(
    (left, right) => (position.get(left.role) ?? Number.MAX_SAFE_INTEGER) - (position.get(right.role) ?? Number.MAX_SAFE_INTEGER),
  );
}

export function normalizeModelSettings(settings: AIModelSettings): AIModelSettings {
  const roleCounts = new Map<string, number>();
  for (const model of settings.models) {
    roleCounts.set(model.role, (roleCounts.get(model.role) ?? 0) + 1);
  }

  const missingRoles = MODEL_ROLE_ORDER.filter((role) => !roleCounts.has(role));
  const duplicateRoles = MODEL_ROLE_ORDER.filter((role) => (roleCounts.get(role) ?? 0) > 1);
  const unexpectedRoles = [...roleCounts.keys()].filter(
    (role) => !MODEL_ROLE_ORDER.includes(role as AIModelRole),
  );
  if (
    settings.models.length !== MODEL_ROLE_ORDER.length ||
    missingRoles.length > 0 ||
    duplicateRoles.length > 0 ||
    unexpectedRoles.length > 0
  ) {
    const details = [
      missingRoles.length > 0 ? `缺少 ${missingRoles.join('、')}` : '',
      duplicateRoles.length > 0 ? `重复 ${duplicateRoles.join('、')}` : '',
      unexpectedRoles.length > 0 ? `包含未知角色 ${unexpectedRoles.join('、')}` : '',
    ].filter(Boolean);
    throw new IncompleteModelSettingsError(details.join('；') || '模型条目数量不正确');
  }

  return { ...settings, models: sortModelSettings(settings.models) };
}

export function shouldSyncModelForm(
  previous: AIModelSetting | null,
  next: AIModelSetting,
): boolean {
  return (
    previous === null ||
    previous.role !== next.role ||
    previous.base_url !== next.base_url ||
    previous.model_name !== next.model_name ||
    previous.api_key_status !== next.api_key_status
  );
}

export function getBaseUrlValidationError(value: string): string | null {
  const candidate = value.trim();
  return candidate.includes('?') || candidate.includes('#')
    ? 'API 地址不能包含查询参数或片段'
    : null;
}

interface ApiKeyValidationInput {
  apiKey: string;
  apiKeyStatus: AIModelKeyStatus;
  baseUrl: string;
  savedBaseUrl: string;
}

export function getApiKeyValidationError({
  apiKey,
  apiKeyStatus,
  baseUrl,
  savedBaseUrl,
}: ApiKeyValidationInput): string | null {
  if (apiKey.trim()) return null;
  if (apiKeyStatus === 'unreadable') {
    return '当前 Key 无法读取，请填写新 API Key';
  }
  if (
    apiKeyStatus === 'configured' &&
    normalizeBaseUrl(baseUrl) !== normalizeBaseUrl(savedBaseUrl)
  ) {
    return 'API 地址已更改，请填写新 API Key';
  }
  return null;
}

export function buildConnectionRequest(values: ModelFormValues): ModelConnectionRequest {
  const apiKey = values.api_key.trim();
  return {
    base_url: normalizeBaseUrl(values.base_url),
    model_name: values.model_name.trim(),
    ...(apiKey ? { api_key: apiKey } : {}),
  };
}

export function clearSensitiveModelFields(values: ModelFormValues): ModelFormValues {
  return { ...values, api_key: '' };
}

export function finalizeConnectionTestFields(
  values: ModelFormValues,
  succeeded: boolean,
): ModelFormValues {
  return succeeded ? { ...values } : clearSensitiveModelFields(values);
}

export function isModelSettingsConflict(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'error_code' in error &&
    (error as { error_code?: unknown }).error_code === 'E4091'
  );
}
