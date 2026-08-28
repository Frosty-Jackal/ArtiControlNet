import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// GitHub Pages 子路径部署时设环境变量 VITE_BASE（如 /arti-controlnet/）
// 后端独立公网地址部署时设 VITE_API_BASE（前端通过该基址访问 /api）
export default defineConfig({
  plugins: [vue()],
  base: process.env.VITE_BASE || '/',
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/images': { target: 'http://localhost:8000', changeOrigin: true }
    }
  }
})
