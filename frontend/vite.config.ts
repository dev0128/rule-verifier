import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 개발: npm run dev → http://127.0.0.1:5180 (API 는 백엔드 8600 으로 프록시)
// 배포형: npm run build → backend 가 frontend/dist 를 그대로 서빙한다 (http://127.0.0.1:8600)
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5180,
    proxy: { '/api': 'http://127.0.0.1:8600' },
  },
})
