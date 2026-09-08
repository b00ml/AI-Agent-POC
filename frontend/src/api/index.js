import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  // M3 全量扫描 / M2 批量审核（含 AI 复核）耗时可达数分钟
  timeout: 300000,
})

api.interceptors.request.use(config => {
  return config
})

api.interceptors.response.use(
  response => response.data,
  error => {
    console.error('API Error:', error.response?.data || error.message)
    return Promise.reject(error)
  }
)

export default api
