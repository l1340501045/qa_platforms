import test from 'node:test';
import assert from 'node:assert/strict';

import {
  IncompleteModelSettingsError,
  MODEL_ROLE_ORDER,
  buildConnectionRequest,
  clearSensitiveModelFields,
  finalizeConnectionTestFields,
  getApiKeyValidationError,
  getBaseUrlValidationError,
  isModelSettingsConflict,
  normalizeModelSettings,
  shouldSyncModelForm,
  sortModelSettings,
} from './modelSettingsModel.ts';
import type { AIModelSetting, AIModelSettings } from '../types/index.ts';

function makeModel(
  role: AIModelSetting['role'],
  overrides: Partial<AIModelSetting> = {},
): AIModelSetting {
  return {
    role,
    display_name: `${role} 模型`,
    description: `${role} 用途`,
    base_url: `https://${role}.example/v1`,
    model_name: `${role}-model`,
    api_key_status: 'configured',
    source: 'database',
    validation_status: 'passed',
    tested_at: '2026-07-20T10:00:00Z',
    vector_dimension: role === 'embedding' ? 1024 : null,
    ...overrides,
  };
}

const completeSettings: AIModelSettings = {
  version_id: 'version-1',
  revision: 1,
  source: 'database',
  persistence_ready: true,
  transport_security: 'trusted_intranet_http',
  models: [
    makeModel('vision'),
    makeModel('embedding'),
    makeModel('primary'),
    makeModel('verify'),
  ],
};

test('模型卡片始终按生成、视觉、校验、向量顺序展示', () => {
  const sorted = sortModelSettings([
    { role: 'embedding', name: '向量' },
    { role: 'verify', name: '校验' },
    { role: 'primary', name: '生成' },
    { role: 'vision', name: '视觉' },
  ]);

  assert.deepEqual(MODEL_ROLE_ORDER, ['primary', 'vision', 'verify', 'embedding']);
  assert.deepEqual(
    sorted.map((item) => item.role),
    MODEL_ROLE_ORDER,
  );
});

test('留空 API Key 时请求不携带 api_key 字段', () => {
  const request = buildConnectionRequest({
    base_url: ' https://gateway.example/v1/ ',
    model_name: ' vision-model ',
    api_key: '   ',
  });

  assert.deepEqual(request, {
    base_url: 'https://gateway.example/v1',
    model_name: 'vision-model',
  });
});

test('填写新 API Key 时请求携带去除首尾空格后的值', () => {
  const request = buildConnectionRequest({
    base_url: 'https://gateway.example/v1',
    model_name: 'vision-model',
    api_key: ' sk-new-secret ',
  });

  assert.equal(request.api_key, 'sk-new-secret');
});

test('连接测试或保存结束后只清空敏感字段', () => {
  const cleared = clearSensitiveModelFields({
    base_url: 'https://gateway.example/v1',
    model_name: 'vision-model',
    api_key: 'sk-new-secret',
  });

  assert.deepEqual(cleared, {
    base_url: 'https://gateway.example/v1',
    model_name: 'vision-model',
    api_key: '',
  });
});

test('新 Key 测试成功后会临时保留并用于紧接着的保存', () => {
  const candidate = {
    base_url: 'https://gateway.example/v1',
    model_name: 'vision-model',
    api_key: 'sk-new-secret',
  };

  const afterSuccessfulTest = finalizeConnectionTestFields(candidate, true);
  assert.equal(buildConnectionRequest(afterSuccessfulTest).api_key, 'sk-new-secret');

  const afterFailedTest = finalizeConnectionTestFields(candidate, false);
  assert.equal(afterFailedTest.api_key, '');
});

test('只把模型配置版本冲突识别为刷新提示', () => {
  assert.equal(isModelSettingsConflict({ error_code: 'E4091' }), true);
  assert.equal(isModelSettingsConflict({ error_code: 'E4221' }), false);
  assert.equal(isModelSettingsConflict(new Error('conflict')), false);
});

test('服务端模型配置必须包含四种角色且每种恰好一条', () => {
  const normalized = normalizeModelSettings(completeSettings);
  assert.deepEqual(
    normalized.models.map((model) => model.role),
    MODEL_ROLE_ORDER,
  );

  assert.throws(
    () =>
      normalizeModelSettings({
        ...completeSettings,
        models: completeSettings.models.filter((model) => model.role !== 'verify'),
      }),
    IncompleteModelSettingsError,
  );

  assert.throws(
    () =>
      normalizeModelSettings({
        ...completeSettings,
        models: completeSettings.models.map((model) =>
          model.role === 'verify' ? makeModel('vision') : model,
        ),
      }),
    IncompleteModelSettingsError,
  );
});

test('其他服务端展示信息变化不会要求回填并覆盖当前卡片输入', () => {
  const previous = makeModel('vision');

  assert.equal(
    shouldSyncModelForm(previous, {
      ...previous,
      tested_at: '2026-07-20T11:00:00Z',
      source: 'environment',
    }),
    false,
  );
  assert.equal(
    shouldSyncModelForm(previous, {
      ...previous,
      base_url: 'https://new-vision.example/v1',
    }),
    true,
  );
  assert.equal(
    shouldSyncModelForm(previous, {
      ...previous,
      api_key_status: 'unreadable',
    }),
    true,
  );
});

test('Key 无法读取或已有 Key 的 API 地址变化时要求就近填写新 Key', () => {
  assert.equal(
    getApiKeyValidationError({
      apiKey: '',
      apiKeyStatus: 'unreadable',
      baseUrl: 'https://gateway.example/v1',
      savedBaseUrl: 'https://gateway.example/v1',
    }),
    '当前 Key 无法读取，请填写新 API Key',
  );
  assert.equal(
    getApiKeyValidationError({
      apiKey: '   ',
      apiKeyStatus: 'configured',
      baseUrl: 'https://new-gateway.example/v1',
      savedBaseUrl: 'https://gateway.example/v1',
    }),
    'API 地址已更改，请填写新 API Key',
  );
  assert.equal(
    getApiKeyValidationError({
      apiKey: '',
      apiKeyStatus: 'configured',
      baseUrl: 'https://gateway.example/v1/',
      savedBaseUrl: 'https://gateway.example/v1',
    }),
    null,
  );
  assert.equal(
    getApiKeyValidationError({
      apiKey: 'sk-new',
      apiKeyStatus: 'unreadable',
      baseUrl: 'https://new-gateway.example/v1',
      savedBaseUrl: 'https://gateway.example/v1',
    }),
    null,
  );
});

test('API 地址禁止携带查询参数或片段', () => {
  assert.equal(
    getBaseUrlValidationError('https://gateway.example/v1?tenant=qa'),
    'API 地址不能包含查询参数或片段',
  );
  assert.equal(
    getBaseUrlValidationError('https://gateway.example/v1#models'),
    'API 地址不能包含查询参数或片段',
  );
  assert.equal(getBaseUrlValidationError('https://gateway.example/v1'), null);
});
