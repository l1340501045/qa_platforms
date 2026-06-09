/**
 * Axios 实例 + 拦截器
 *
 * 对齐契约：
 * - 成功响应：{code:0, message:"success", data:{...}} → 拦截器返回 data
 * - 错误响应：{error_code, message, request_id} → reject ApiError
 */
import axios, { type AxiosError } from 'axios';
import { message } from 'antd';
import type { ApiResponse, ApiError } from '../types';
import { v4 as uuidv4 } from 'uuid';

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器 — 注入 X-Request-ID
api.interceptors.request.use((config) => {
  config.headers['X-Request-ID'] = uuidv4();
  return config;
});

// 响应拦截器 — 解包信封，统一错误处理
api.interceptors.response.use(
  (response) => {
    // 204 No Content（DELETE 成功）
    if (response.status === 204) {
      return response;
    }

    const body = response.data as ApiResponse<unknown>;

    // 成功信封：{code:0, message:"success", data:{...}}
    if (body && body.code === 0 && 'data' in body) {
      // 返回解包后的 data 作为 response.data
      response.data = body.data;
      return response;
    }

    // 非标准成功（兜底），直接透传
    return response;
  },
  (error: AxiosError<ApiError>) => {
    const status = error.response?.status;
    const errorData = error.response?.data;

    if (errorData && errorData.error_code) {
      // 契约错误结构：{error_code, message, request_id}
      const { error_code, message: errorMsg } = errorData;

      switch (status) {
        case 400:
          message.error(errorMsg || '请求参数无效');
          break;
        case 404:
          // 页面级处理，不弹 toast
          break;
        case 409:
          message.error(errorMsg || '资源冲突');
          break;
        case 413:
          message.error('文件超过 100MB 限制');
          break;
        case 422:
          message.error(errorMsg || '请求格式错误');
          break;
        case 429:
          message.warning('请求过于频繁，请稍后重试');
          break;
        case 500:
          message.error('服务器错误，请稍后重试');
          break;
        case 503:
          message.error('服务暂时不可用');
          break;
        default:
          message.error(errorMsg || '请求失败');
      }

      console.error(`[API Error] ${error_code}: ${errorMsg} (request_id: ${errorData.request_id})`);
      return Promise.reject(errorData);
    }

    // 网络错误
    if (!error.response) {
      message.error('网络连接失败，请检查网络');
    }

    return Promise.reject(error);
  },
);

export default api;
