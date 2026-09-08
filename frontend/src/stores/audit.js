import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'
import { useConnectionStore } from './connection'

export const useAuditStore = defineStore('audit', () => {
  const claims = ref([])
  const allClaims = ref([])
  const loading = ref(false)
  const currentClaim = ref(null)
  const auditResults = ref([])
  const auditStatusMap = ref({})
  const selectedIds = ref([])

  // 分页状态
  const currentPage = ref(1)
  const totalCount = ref(0)
  const hasMore = ref(false)
  const nextCursor = ref(null)
  const pageCursors = ref({ 1: null })
  const lastStatus = ref(null)

  const stats = computed(() => {
    const list = allClaims.value.length ? allClaims.value : claims.value
    let approved = 0
    let rejected = 0
    let flagged = 0
    for (const c of list) {
      const s = auditStatusMap.value[c.id || c.claimNo]
      if (s?.result === 'APPROVE') approved++
      else if (s?.result === 'REJECT') rejected++
      else if (s?.result === 'FLAG') flagged++
    }
    const total = list.length
    return { total, approved, rejected, flagged }
  })

  // 拉取当前状态下的全部单据（用于总单数与统计；分页展示仍用 loadClaims）
  async function loadAll(status = null) {
    const connStore = useConnectionStore()
    const items = []
    let cursor = null
    let hasMore = true
    while (hasMore) {
      const params = {
        api_url: connStore.apiUrl,
        api_key: connStore.apiKey,
        limit: 200,
      }
      if (status) params.status = status
      if (cursor) params.cursor = cursor
      const d = await api.get('/erp/claims', { params })
      items.push(...(d.items || []))
      hasMore = !!d.hasMore
      cursor = d.nextCursor || null
    }
    allClaims.value = items
    totalCount.value = items.length
    return items
  }

  async function loadClaims(params = {}) {
    loading.value = true
    try {
      const connStore = useConnectionStore()
      await loadAuditStatus()
      const pageSize = params.pageSize || 30
      const page = params.page || 1
      const status = (params.status && params.status !== 'ALL') ? params.status : null

      // 状态变化时重置游标链
      if (status !== lastStatus.value) {
        pageCursors.value = { 1: null }
        lastStatus.value = status
        await loadAll(status)
      }

      const cursor = params.cursor !== undefined
        ? params.cursor
        : (pageCursors.value[page] ?? null)
      const reqParams = {
        api_url: connStore.apiUrl,
        api_key: connStore.apiKey,
        limit: pageSize,
        cursor,
      }
      if (status) reqParams.status = status

      const data = await api.get('/erp/claims', { params: reqParams })
      const items = data.items || []
      // 分页：每页替换当前页数据
      claims.value = items
      hasMore.value = !!data.hasMore
      nextCursor.value = data.nextCursor || null
      currentPage.value = page
      if (data.nextCursor) {
        pageCursors.value[page + 1] = data.nextCursor
      }
      // 总条数以全量拉取结果为准
      if (totalCount.value === 0) {
        await loadAll(status)
      }
      return data
    } finally {
      loading.value = false
    }
  }

  async function runAudit(claimIds, onProgress = null, writeBack = false) {
    try {
      const connStore = useConnectionStore()
      const resp = await api.post('/m2/audit', {
        claimIds,
        apiUrl: connStore.apiUrl,
        apiKey: connStore.apiKey,
        writeBack,
      }, { timeout: 30000 })
      // 异步任务：有限轮询，避免服务异常时页面永久挂起
      const jobId = resp.jobId
      const deadline = Date.now() + 30 * 60 * 1000
      let delay = 1000
      while (Date.now() < deadline) {
        const s = await api.get('/m2/audit-status/' + jobId, { timeout: 30000 })
        if (s.status === 'done') {
          auditResults.value = s.results?.results || []
          await loadAuditStatus()
          if (onProgress) onProgress({ processed: s.total, total: s.total, phase: 'done' })
          return s.results || { results: [], total: 0 }
        }
        if (['error', 'cancelled', 'dead'].includes(s.status)) {
          throw new Error(s.error || '审核失败')
        }
        if (onProgress) onProgress({
          processed: s.processed || 0,
          total: s.total || claimIds.length,
          phase: s.phase || 'rules',
        })
        await new Promise(r => setTimeout(r, delay))
        delay = Math.min(5000, Math.round(delay * 1.4))
      }
      throw new Error('审核任务等待超时，请到任务状态页查看结果')
    } catch (e) {
      throw e
    }
  }

  async function cancelAudit(jobId) {
    return api.post('/m2/audit-status/' + jobId + '/cancel')
  }

  async function submitReview(claimId, payload) {
    const connStore = useConnectionStore()
    const data = await api.post('/m2/review', {
      claimId,
      apiUrl: connStore.apiUrl,
      apiKey: connStore.apiKey,
      ...payload,
    })
    return data
  }

  async function loadAuditStatus() {
    try {
      const resp = await api.get('/m2/status')
      auditStatusMap.value = resp.status || {}
    } catch (e) {
      // 状态接口不可用时静默降级，列表仍可正常展示
    }
  }

  function selectClaims(ids) {
    selectedIds.value = ids
  }

  return {
    claims, allClaims, loading, currentClaim, auditResults, auditStatusMap, selectedIds, stats,
    currentPage, totalCount, hasMore, nextCursor,
    loadClaims, loadAll, runAudit, cancelAudit, submitReview, selectClaims, loadAuditStatus,
  }
})
