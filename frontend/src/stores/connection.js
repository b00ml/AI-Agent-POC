import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '../api'

export const useConnectionStore = defineStore('connection', () => {
  const demoMode = import.meta.env.VITE_DEMO_MODE === '1'
  const connected = ref(false)
  const connecting = ref(false)
  const apiUrl = ref(demoMode ? 'demo://local' : 'http://host.docker.internal:8081')
  const apiKey = ref(demoMode ? 'demo' : '')
  const error = ref('')

  async function init() {
    if (demoMode) {
      // Demo uses an in-process synthetic ERP adapter; no credential is read
      // from localStorage and the UI is immediately ready for exploration.
      connected.value = true
      return
    }
    const savedKey = localStorage.getItem('qiheng_api_key')
    const savedUrl = localStorage.getItem('qiheng_api_url')
    if (savedKey) apiKey.value = savedKey
    if (savedUrl) apiUrl.value = savedUrl
  }

  async function connect() {
    connecting.value = true
    error.value = ''
    try {
      await api.post('/erp/connect', {
        api_url: apiUrl.value,
        api_key: apiKey.value,
      })
      connected.value = true
      localStorage.setItem('qiheng_api_key', apiKey.value)
      localStorage.setItem('qiheng_api_url', apiUrl.value)
    } catch (e) {
      // API v3 returns { code, message, requestId, details }; retain the
      // legacy detail fallback while older backends are still supported.
      error.value = e.response?.data?.message || e.response?.data?.detail || '连接失败'
      connected.value = false
    } finally {
      connecting.value = false
    }
  }

  function disconnect() {
    connected.value = false
    apiKey.value = ''
    error.value = ''
    localStorage.removeItem('qiheng_api_key')
  }

  return { connected, connecting, apiUrl, apiKey, error, demoMode, init, connect, disconnect }
})
