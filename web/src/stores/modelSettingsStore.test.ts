import test from 'node:test';
import assert from 'node:assert/strict';

import { createModelSettingsStore } from './modelSettingsStore.ts';
import type {
  AIModelRole,
  AIModelSetting,
  AIModelSettings,
  ModelConnectionRequest,
  SaveModelSettingRequest,
} from '../types/index.ts';

function makeModel(role: AIModelRole): AIModelSetting {
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
  };
}

const settings: AIModelSettings = {
  version_id: 'version-1',
  revision: 1,
  source: 'database',
  persistence_ready: true,
  transport_security: 'trusted_intranet_http',
  models: [makeModel('primary'), makeModel('vision'), makeModel('verify'), makeModel('embedding')],
};

test('store 区分首次加载失败和空配置', async () => {
  const store = createModelSettingsStore({
    getSettings: async () => {
      throw new Error('服务不可达');
    },
    testConnection: async () => {
      throw new Error('not used');
    },
    saveSetting: async () => {
      throw new Error('not used');
    },
  });

  await assert.rejects(store.getState().fetchSettings(), /服务不可达/);

  assert.equal(store.getState().settings, null);
  assert.equal(store.getState().loading, false);
  assert.equal(store.getState().loadError, '服务不可达');
});

test('连接测试结束后 store 不保留 API Key', async () => {
  let capturedRequest: ModelConnectionRequest | null = null;
  const store = createModelSettingsStore({
    getSettings: async () => settings,
    testConnection: async (_role, request) => {
      capturedRequest = request;
      return {
        ok: true,
        category: 'success',
        message: '连接成功',
        latency_ms: 18,
        embedding_dimension: null,
      };
    },
    saveSetting: async () => settings,
  });

  await store.getState().testModel('vision', {
    base_url: 'https://vision.example/v1',
    model_name: 'vision-model',
    api_key: 'sk-never-store-me',
  });

  assert.equal(capturedRequest?.api_key, 'sk-never-store-me');
  assert.equal(store.getState().operations.vision.testing, false);
  assert.equal(store.getState().operations.vision.lastTest?.ok, true);
  assert.equal(JSON.stringify(store.getState()).includes('sk-never-store-me'), false);
});

test('候选值变化只清除当前卡片的过期测试反馈', async () => {
  const store = createModelSettingsStore({
    getSettings: async () => settings,
    testConnection: async (role) => ({
      ok: true,
      category: 'success',
      message: `${role} 连接成功`,
      latency_ms: 18,
      embedding_dimension: role === 'embedding' ? 1024 : null,
    }),
    saveSetting: async () => settings,
  });

  await store.getState().testModel('primary', {
    base_url: 'https://primary.example/v1',
    model_name: 'primary-model',
  });
  await store.getState().testModel('vision', {
    base_url: 'https://vision.example/v1',
    model_name: 'vision-model',
  });

  store.getState().clearLastTest('vision');

  assert.equal(store.getState().operations.vision.lastTest, null);
  assert.equal(store.getState().operations.primary.lastTest?.ok, true);
});

test('服务端缺少或重复模型角色时进入配置不完整错误态', async () => {
  for (const invalidModels of [
    settings.models.filter((model) => model.role !== 'verify'),
    settings.models.map((model) =>
      model.role === 'verify' ? makeModel('vision') : model,
    ),
  ]) {
    const store = createModelSettingsStore({
      getSettings: async () => ({ ...settings, models: invalidModels }),
      testConnection: async () => {
        throw new Error('not used');
      },
      saveSetting: async () => {
        throw new Error('not used');
      },
    });

    await assert.rejects(store.getState().fetchSettings(), /模型配置不完整/);

    assert.equal(store.getState().settings, null);
    assert.equal(store.getState().loadErrorKind, 'incomplete');
    assert.match(store.getState().loadError ?? '', /模型配置不完整/);
  }
});

test('保存成功后用服务端新版本替换当前设置', async () => {
  const nextSettings = { ...settings, version_id: 'version-2', revision: 2 };
  let capturedRequest: SaveModelSettingRequest | null = null;
  const store = createModelSettingsStore({
    getSettings: async () => settings,
    testConnection: async () => {
      throw new Error('not used');
    },
    saveSetting: async (_role, request) => {
      capturedRequest = request;
      return nextSettings;
    },
  });

  await store.getState().saveModel('vision', {
    base_url: 'https://vision.example/v1',
    model_name: 'vision-model-v2',
    api_key: 'sk-never-store-me',
    expected_revision: 1,
  });

  assert.equal(capturedRequest?.expected_revision, 1);
  assert.equal(store.getState().settings?.revision, 2);
  assert.equal(store.getState().operations.vision.saving, false);
  assert.equal(JSON.stringify(store.getState()).includes('sk-never-store-me'), false);
});
