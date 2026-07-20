import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        // 保留浏览器侧 Host，确保无鉴权阶段的模型设置接口可做同源校验。
        changeOrigin: false,
      },
    },
  },
});
