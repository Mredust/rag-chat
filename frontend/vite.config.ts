import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 4041,
    proxy: {
      // 前端请求 /api 时，代理到后端 FastAPI 服务（端口与 main.py 保持一致）
      '/api': {
        target: 'http://127.0.0.1:4040',
        changeOrigin: true,
      },
    },
  },
})