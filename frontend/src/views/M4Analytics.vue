<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const running = ref(false)
const data = ref(null)

const stats = computed(() => {
  const matches = data.value?.matches || []
  const unidentified = data.value?.unidentified || []
  const stat = data.value?.statistics || {}
  return {
    matched: matches.length,
    unidentified: unidentified.length,
    total: matches.length + unidentified.length,
    rate: stat.matchedRate != null
      ? (stat.matchedRate * 100).toFixed(1)
      : (matches.length / (matches.length + unidentified.length) * 100).toFixed(1),
    byReason: stat.unidentifiedByReason || [],
  }
})

function fmtError(e) {
  const body = e?.response?.data
  if (typeof body?.message === 'string' && body.message) return body.message
  const detail = body?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) return detail.map(d => d?.msg || JSON.stringify(d)).join('; ')
  if (detail) return JSON.stringify(detail)
  return e?.message || '请求失败'
}

async function reconcile() {
  running.value = true
  try {
    const res = await api.post('/m4/reconcile', {})
    data.value = res
    ElMessage.success(`对账完成：匹配 ${stats.value.matched} 笔，未识别 ${stats.value.unidentified} 笔`)
  } catch (e) {
    ElMessage.error('对账失败: ' + fmtError(e))
  } finally {
    running.value = false
  }
}
</script>

<template>
  <div class="m4-analytics-page">
    <header class="page-header">
      <div>
        <h1 class="page-title">M4 银行对账</h1>
        <p class="page-subtitle">银行流水 CSV × 应收台账自动匹配（别名/容差/一笔多票；宁缺毋滥，不确定的列入待认领）</p>
      </div>
      <button class="btn-primary" :disabled="running" @click="reconcile">
        <el-icon v-if="!running"><Refresh /></el-icon>
        <span style="margin-left: 6px">{{ running ? '对账中...' : '开始对账' }}</span>
      </button>
    </header>

    <div class="kpi-row four">
      <div class="kpi-card glass-card">
        <div class="kpi-value mono" style="color: var(--success)">{{ stats.rate }}%</div>
        <div class="kpi-label">自动匹配率</div>
      </div>
      <div class="kpi-card glass-card">
        <div class="kpi-value mono">{{ stats.matched }}</div>
        <div class="kpi-label">自动匹配(笔)</div>
      </div>
      <div class="kpi-card glass-card">
        <div class="kpi-value mono" style="color: var(--warning)">{{ stats.unidentified }}</div>
        <div class="kpi-label">待人工认领(笔)</div>
      </div>
      <div class="kpi-card glass-card">
        <div class="kpi-value mono">{{ stats.total }}</div>
        <div class="kpi-label">收款流水总数</div>
      </div>
    </div>

    <div class="charts-row">
      <div class="chart-card glass-card">
        <h3 class="chart-title">自动匹配明细（{{ stats.matched }}）</h3>
        <div v-if="data && stats.matched" class="match-list">
          <div v-for="(m, i) in data.matches.slice(0, 200)" :key="'m' + i" class="match-row">
            <span class="mono txn">{{ m.txnId }}</span>
            <span class="arrow">→</span>
            <span class="mono ar">{{ (m.receivableIds || []).join(', ') }}</span>
            <span v-if="m.note" class="tag-pill">{{ m.note }}</span>
          </div>
        </div>
        <div v-else class="placeholder-content">
          <el-icon :size="48" class="placeholder-icon"><Connection /></el-icon>
          <p>点击「开始对账」执行匹配</p>
        </div>
      </div>

      <div class="chart-card glass-card">
        <h3 class="chart-title">待人工认领（{{ stats.unidentified }}）</h3>
        <div v-if="stats.byReason.length" class="reason-badges">
          <span v-for="r in stats.byReason" :key="r.category" class="reason-badge">
            {{ r.label }}：<b class="mono">{{ r.count }}</b> 笔
          </span>
        </div>
        <div v-if="data && stats.unidentified" class="match-list">
          <div v-for="(t, i) in data.unidentified.slice(0, 200)" :key="'u' + i" class="match-row">
            <span class="mono txn">{{ typeof t === 'string' ? t : t.txnId }}</span>
            <span class="tag-pill">{{ typeof t === 'string' ? '名称/金额/日期无法唯一确认' : (t.reason || '待人工认领') }}</span>
          </div>
        </div>
        <div v-else-if="data" class="placeholder-content">
          <el-icon :size="48" class="placeholder-icon"><CircleCheck /></el-icon>
          <p>全部流水均已匹配</p>
        </div>
        <div v-else class="placeholder-content">
          <el-icon :size="48" class="placeholder-icon"><Connection /></el-icon>
          <p>点击「开始对账」执行匹配</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.m4-analytics-page { max-width: 1400px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
.page-title { font-family: var(--font-display); font-size: 28px; font-weight: 700; color: var(--text-primary); margin: 0; }
.page-subtitle { font-size: 14px; color: var(--text-muted); margin-top: 4px; }
.kpi-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 24px; }
.kpi-row.four { grid-template-columns: repeat(4, 1fr); }
.kpi-card { padding: 20px; text-align: center; }
.kpi-value { font-size: 32px; font-weight: 700; color: var(--text-primary); }
.kpi-label { font-size: 13px; color: var(--text-muted); margin: 4px 0 8px; }
.charts-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.chart-card { padding: 24px; }
.chart-title { font-family: var(--font-display); font-size: 15px; font-weight: 600; margin: 0 0 16px; }
.match-list { max-height: 520px; overflow: auto; display: flex; flex-direction: column; gap: 8px; }
.reason-badges { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.reason-badge { font-size: 12px; color: var(--text-secondary); background: var(--bg-tertiary); border: 1px solid var(--border); border-radius: 12px; padding: 4px 10px; }
.reason-badge b { color: var(--warning); }
.match-row { display: flex; align-items: center; gap: 10px; font-size: 12px; padding: 8px 10px; background: var(--bg-tertiary); border-radius: 6px; }
.txn { color: var(--text-primary); }
.ar { color: var(--brand); }
.arrow { color: var(--text-muted); }
.tag-pill { color: var(--warning); font-size: 11px; margin-left: auto; }
.placeholder-content { display: flex; flex-direction: column; align-items: center; padding: 60px 0; gap: 12px; color: var(--text-muted); }
.placeholder-icon { color: var(--brand); opacity: 0.3; }
.placeholder-content p { margin: 0; font-size: 14px; }
</style>
