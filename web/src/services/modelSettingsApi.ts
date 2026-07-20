import type {
  AIModelRole,
  AIModelSettings,
  ModelConnectionRequest,
  ModelConnectionTestResult,
  SaveModelSettingRequest,
} from '../types';
import api from './api';

export async function getAIModelSettings(): Promise<AIModelSettings> {
  const response = await api.get('/settings/ai-models');
  return response.data;
}

export async function testModelConnection(
  role: AIModelRole,
  request: ModelConnectionRequest,
): Promise<ModelConnectionTestResult> {
  const response = await api.post(`/settings/ai-models/${role}/test`, request);
  return response.data;
}

export async function saveModelSetting(
  role: AIModelRole,
  request: SaveModelSettingRequest,
): Promise<AIModelSettings> {
  const response = await api.put(`/settings/ai-models/${role}`, request);
  return response.data;
}

export const modelSettingsApi = {
  getSettings: getAIModelSettings,
  testConnection: testModelConnection,
  saveSetting: saveModelSetting,
};
