import { create, type StoreApi, type UseBoundStore } from 'zustand';

import type {
  AIModelRole,
  AIModelSettings,
  ModelConnectionRequest,
  ModelConnectionTestResult,
  SaveModelSettingRequest,
} from '../types';
import {
  IncompleteModelSettingsError,
  normalizeModelSettings,
} from '../services/modelSettingsModel.ts';

export interface ModelSettingsGateway {
  getSettings: () => Promise<AIModelSettings>;
  testConnection: (
    role: AIModelRole,
    request: ModelConnectionRequest,
  ) => Promise<ModelConnectionTestResult>;
  saveSetting: (
    role: AIModelRole,
    request: SaveModelSettingRequest,
  ) => Promise<AIModelSettings>;
}

interface ModelOperationState {
  testing: boolean;
  saving: boolean;
  lastTest: ModelConnectionTestResult | null;
}

interface ModelSettingsState {
  settings: AIModelSettings | null;
  loading: boolean;
  loadError: string | null;
  loadErrorKind: 'load' | 'incomplete' | null;
  operations: Record<AIModelRole, ModelOperationState>;
  fetchSettings: () => Promise<void>;
  testModel: (
    role: AIModelRole,
    request: ModelConnectionRequest,
  ) => Promise<ModelConnectionTestResult | undefined>;
  saveModel: (
    role: AIModelRole,
    request: SaveModelSettingRequest,
  ) => Promise<AIModelSettings | undefined>;
  clearLastTest: (role: AIModelRole) => void;
}

export type ModelSettingsStore = UseBoundStore<StoreApi<ModelSettingsState>>;

const defaultGateway: ModelSettingsGateway = {
  getSettings: async () => (await import('../services/modelSettingsApi.ts')).getAIModelSettings(),
  testConnection: async (role, request) =>
    (await import('../services/modelSettingsApi.ts')).testModelConnection(role, request),
  saveSetting: async (role, request) =>
    (await import('../services/modelSettingsApi.ts')).saveModelSetting(role, request),
};

const emptyOperation = (): ModelOperationState => ({
  testing: false,
  saving: false,
  lastTest: null,
});

export function createModelSettingsStore(
  gateway: ModelSettingsGateway = defaultGateway,
): ModelSettingsStore {
  return create<ModelSettingsState>((set) => ({
    settings: null,
    loading: false,
    loadError: null,
    loadErrorKind: null,
    operations: {
      primary: emptyOperation(),
      vision: emptyOperation(),
      verify: emptyOperation(),
      embedding: emptyOperation(),
    },
    fetchSettings: async () => {
      set({ loading: true, loadError: null, loadErrorKind: null });
      try {
        const settings = await gateway.getSettings();
        set({ settings: normalizeModelSettings(settings) });
      } catch (error) {
        const incomplete = error instanceof IncompleteModelSettingsError;
        const loadError = incomplete
          ? error.message
          : typeof error === 'object' &&
              error !== null &&
              'message' in error &&
              typeof (error as { message?: unknown }).message === 'string'
            ? (error as { message: string }).message
            : '模型设置暂时无法加载，请重试。';
        set({ settings: null, loadError, loadErrorKind: incomplete ? 'incomplete' : 'load' });
        throw error;
      } finally {
        set({ loading: false });
      }
    },
    testModel: async (role, request) => {
      set((state) => ({
        operations: {
          ...state.operations,
          [role]: { ...state.operations[role], testing: true, lastTest: null },
        },
      }));
      try {
        const result = await gateway.testConnection(role, request);
        set((state) => ({
          operations: {
            ...state.operations,
            [role]: { ...state.operations[role], lastTest: result },
          },
        }));
        return result;
      } finally {
        set((state) => ({
          operations: {
            ...state.operations,
            [role]: { ...state.operations[role], testing: false },
          },
        }));
      }
    },
    saveModel: async (role, request) => {
      set((state) => ({
        operations: {
          ...state.operations,
          [role]: { ...state.operations[role], saving: true },
        },
      }));
      try {
        const settings = await gateway.saveSetting(role, request);
        const normalizedSettings = normalizeModelSettings(settings);
        set((state) => ({
          settings: normalizedSettings,
          operations: {
            ...state.operations,
            [role]: { ...state.operations[role], lastTest: null },
          },
        }));
        return normalizedSettings;
      } finally {
        set((state) => ({
          operations: {
            ...state.operations,
            [role]: { ...state.operations[role], saving: false },
          },
        }));
      }
    },
    clearLastTest: (role) => {
      set((state) => ({
        operations: {
          ...state.operations,
          [role]: { ...state.operations[role], lastTest: null },
        },
      }));
    },
  }));
}

export const useModelSettingsStore = createModelSettingsStore();
