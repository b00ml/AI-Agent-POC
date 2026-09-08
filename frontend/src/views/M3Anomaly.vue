<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useConnectionStore } from '../stores/connection'
import api from '../api'

const connStore = useConnectionStore()
const scanning = ref(false)
const data = ref(null)
const detailVisible = ref(false)
const detailTitle = ref('')
const detailInvoices = ref([])
const detailBasis = ref('')
const detailAi = ref(null)
const aiReview = ref(null)
const reviewing = ref(false)
const reviewProgress = ref({ processed: 0, total: 0 })
const aiScan = ref(null)
const aiScanning = ref(false)
const aiScanProgress = ref({ processed: 0, total: 0 })
const scanLimit = ref(300)

const stats = computed(() => {
  const dups = data.value?.duplicateInvoices?.length || 0
  const issues = data.value?.invoiceIssues || []
  return {
    total: dups + issues.length,
    duplicate: dups,
    title: issues.filter(i => i.issue === 'TITLE_WRONG').length,
    taxno: issues.filter(i => i.issue === 'TAXNO_WRONG').length,
    rate: issues.filter(i => i.issue === 'TAX_RATE_WRONG').length,
  }
})

const issueLabels = {
  TITLE_WRONG: '抬头错误',
  TAXNO_WRONG: '税号错误',
  TAX_RATE_WRONG: '税率异常',
  CONSECUTIVE_NO: '疑似连号',
  SUPPLIER_DUP: '供应商重复档案',
}

const aiLabels = {
  CONFIRM: { label: 'AI确认', type: 'success' },
  DOUBT: { label: 'AI存疑', type: 'warning' },
  FALSE_ALARM: { label: 'AI误报', type: 'danger' },
}

const scanTypeMeta = {
  TAX_RATE_WRONG: { label: '税率异常', type: 'warning' },
  TITLE_WRONG: { label: '抬头错误', type: 'danger' },
  TAXNO_WRONG: { label: '税号错误', type: 'danger' },
  DUPLICATE: { label: '疑似重复', type: 'danger' },
  AMOUNT_ABNORMAL: { label: '金额异常', type: 'warning' },
  KIND_MISMATCH: { label: '票种不符', type: 'info' },
  DATE_ABNORMAL: { label: '日期异常', type: 'warning' },
  CONSECUTIVE_NO: { label: '连号发票', type: 'warning' },
  OTHER: { label: '其他异常', type: 'info' },
}

function aiVerdictFor(item, kind) {
  if (!aiReview.value?.results) return null
  const key = kind === 'issue'
    ? `issue:${item.issue}:${item.invoiceId}`
    : `duplicate:${item.invoiceCode}/${item.invoiceNo}`
  return aiReview.value.results[key] || null
}

function fmtError(e) {
  const body = e?.response?.data
  if (typeof body?.message === 'string' && body.message) return body.message
  const detail = body?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) return detail.map(d => d?.msg || JSON.stringify(d)).join('; ')
  if (detail) return JSON.stringify(detail)
  return e?.message || '请求失败'
}

async function scan(useCached = false) {
  if (!connStore.connected) {
    ElMessage.warning('请先连接 ERP：M2 页面右上角「连接 ERP」，填写 API 地址与 Key')
    return
  }
  scanning.value = true
  try {
    const res = await api.post('/m3/scan', {
      apiUrl: connStore.apiUrl,
      apiKey: connStore.apiKey,
      scope: 'all',
      useCached,
    })
    data.value = res
    ElMessage.success(
      useCached
        ? `已加载最近一次扫描结果：重复发票 ${stats.value.duplicate} 组，票面问题 ${stats.value.total - stats.value.duplicate} 项`
        : `扫描完成：重复发票 ${stats.value.duplicate} 组，票面问题 ${stats.value.total - stats.value.duplicate} 项`
    )
  } catch (e) {
    ElMessage.error('扫描失败: ' + fmtError(e))
  } finally {
    scanning.value = false
  }
}

async function runAiReview() {
  if (!connStore.connected) {
    ElMessage.warning('请先连接 ERP')
    return
  }
  reviewing.value = true
  reviewProgress.value = { processed: 0, total: 0 }
  try {
    const resp = await api.post('/m3/ai-review', {
      apiUrl: connStore.apiUrl,
      apiKey: connStore.apiKey,
      scope: 'all',
      useCached: false,
    }, { timeout: 30000 })
    const jobId = resp.jobId
    let res = null
    for (;;) {
      const s = await api.get('/m3/ai-review-status/' + jobId, { timeout: 30000 })
      if (s.status === 'done') {
        res = s.results
        reviewProgress.value = { processed: s.total, total: s.total }
        break
      }
      if (s.status === 'error') {
        throw new Error(s.error || 'AI 复核失败')
      }
      reviewProgress.value = { processed: s.processed || 0, total: s.total || 0 }
      await new Promise(r => setTimeout(r, 2500))
    }
    aiReview.value = res
    const verdicts = Object.values(res.results || {}).map(r => r?.verdict).filter(Boolean)
    const count = v => verdicts.filter(x => x === v).length
    ElMessage.success(`AI 复核完成：确认 ${count('CONFIRM')}，存疑 ${count('DOUBT')}，误报 ${count('FALSE_ALARM')}`)
  } catch (e) {
    ElMessage.error('AI 复核失败: ' + fmtError(e))
  } finally {
    reviewing.value = false
  }
}

async function loadAiReview() {
  try {
    const res = await api.get('/m3/ai-review-results')
    if (res?.results && Object.keys(res.results).length) {
      aiReview.value = res
    }
  } catch (e) {
    console.warn('AI 复核结果加载失败', e)
  }
}

async function runAiScan() {
  if (!connStore.connected) {
    ElMessage.warning('请先连接 ERP')
    return
  }
  aiScanning.value = true
  aiScanProgress.value = { processed: 0, total: 0 }
  try {
    const resp = await api.post('/m3/ai-scan', {
      apiUrl: connStore.apiUrl,
      apiKey: connStore.apiKey,
      scope: 'all',
      limit: scanLimit.value === 'all' ? null : Number(scanLimit.value),
      batchSize: 60,
      useCached: true,
    }, { timeout: 30000 })
    const jobId = resp.jobId
    let res = null
    for (;;) {
      const s = await api.get('/m3/ai-scan-status/' + jobId, { timeout: 30000 })
      if (s.status === 'done') {
        res = s.results
        break
      }
      if (s.status === 'error') {
        throw new Error(s.error || 'AI 巡检失败')
      }
      aiScanProgress.value = { processed: s.processed || 0, total: s.total || 0 }
      await new Promise(r => setTimeout(r, 2500))
    }
    aiScan.value = res
    aiScanProgress.value = { processed: res?.batchCount || 0, total: res?.batchCount || 0 }
    ElMessage.success(`AI 巡检完成：扫描 ${res?.totalInvoices || 0} 张发票，发现疑似异常 ${res?.flaggedCount || 0} 项`)
  } catch (e) {
    ElMessage.error('AI 巡检失败: ' + fmtError(e))
  } finally {
    aiScanning.value = false
  }
}

async function loadAiScan() {
  try {
    const res = await api.get('/m3/ai-scan-results')
    if (res?.flaggedCount || res?.flagged?.length) {
      aiScan.value = res
    }
  } catch (e) {
    console.warn('AI 巡检结果加载失败', e)
  }
}

function viewInvoices(invoices, title) {
  detailInvoices.value = invoices || []
  detailTitle.value = title
  detailVisible.value = true
}

function viewDuplicate(dup) {
  viewInvoices(dup.invoices || [], `重复发票 ${dup.invoiceCode} / ${dup.invoiceNo}`)
  detailBasis.value = dup.basis || '依据《费用报销管理办法 V3.2》第十七条：同一张发票不得重复报销'
  detailAi.value = aiVerdictFor(dup, 'duplicate')
}

function viewIssue(item) {
  const invs = item.issue === 'SUPPLIER_DUP'
    ? (item.invoices || [])
    : (item.invoice ? [item.invoice] : [])
  viewInvoices(invs, `${issueLabels[item.issue] || item.issue} ${item.invoiceId}`)
  detailBasis.value = item.basis || ''
  detailAi.value = aiVerdictFor(item, 'issue')
}

function viewSupplierProfile(prof) {
  viewInvoices(prof.invoices || [], `供应商画像 ${prof.sellerName}`)
  detailBasis.value = prof.basis || ''
  detailAi.value = null
}

function viewAiFlag(item) {
  viewInvoices(
    item.invoice ? [item.invoice] : [],
    `AI巡检 ${scanTypeMeta[item.type]?.label || item.type} ${item.invoiceId}`,
  )
  detailBasis.value = item.reason || ''
  detailAi.value = null
}

function openImg(attachmentId) {
  if (attachmentId) {
    window.open(`/api/erp/attachments/${attachmentId}/content`, '_blank')
  }
}

function yuan(fen) {
  if (fen == null) return '-'
  return (fen / 100).toFixed(2)
}

onMounted(() => {
  if (connStore.connected) scan(true)
  loadAiReview()
  loadAiScan()
})
</script>

<template>
  <div class="m3-anomaly-page">
    <header class="page-header">
      <div>
        <h1 class="page-title">M3 发票异常检测</h1>
        <p class="page-subtitle">全量发票台账稽核：重复报销、抬头/税号错误、税率异常（以系统记录为准）</p>
      </div>
      <div class="header-actions">
        <el-select
          v-model="scanLimit"
          style="width: 128px"
          :disabled="aiScanning || scanning || reviewing"
        >
          <el-option label="全量发票" value="all" />
          <el-option label="前300张" value="300" />
          <el-option label="前100张" value="100" />
        </el-select>
        <button class="btn-secondary" :disabled="aiScanning || scanning" @click="runAiScan">
          <el-icon v-if="!aiScanning"><MagicStick /></el-icon>
          <span style="margin-left: 6px">
            {{ aiScanning ? `AI 巡检中 ${aiScanProgress.processed}/${aiScanProgress.total || '...'}` : 'AI 全量巡检' }}
          </span>
        </button>
        <button class="btn-secondary" :disabled="reviewing || !data" @click="runAiReview">
          <el-icon v-if="!reviewing"><MagicStick /></el-icon>
          <span style="margin-left: 6px">
            {{ reviewing ? `AI 复核中 ${reviewProgress.processed}/${reviewProgress.total || '...'}` : 'AI 复核异常' }}
          </span>
        </button>
        <button class="btn-primary" :disabled="scanning" @click="scan(false)">
          <el-icon v-if="!scanning"><Refresh /></el-icon>
          <span style="margin-left: 6px">{{ scanning ? '扫描中...' : '开始全量扫描' }}</span>
        </button>
      </div>
    </header>

    <div class="stats-row">
      <div class="stat-card glass-card">
        <div class="stat-value mono">{{ stats.total }}</div>
        <div class="stat-label">异常总数</div>
      </div>
      <div class="stat-card glass-card">
        <div class="stat-value mono danger">{{ stats.duplicate }}</div>
        <div class="stat-label">重复发票(组)</div>
      </div>
      <div class="stat-card glass-card">
        <div class="stat-value mono warning">{{ stats.title + stats.taxno }}</div>
        <div class="stat-label">抬头/税号问题</div>
      </div>
      <div class="stat-card glass-card">
        <div class="stat-value mono" style="color: var(--text-secondary)">{{ stats.rate }}</div>
        <div class="stat-label">税率异常</div>
      </div>
    </div>

    <div class="results-panel glass-card">
      <div class="panel-header">
        <h3>异常检测结果</h3>
        <div class="panel-right">
          <span v-if="data?.fromCache" class="cache-tag">最近一次扫描结果</span>
          <span v-if="data" class="result-count">{{ stats.total }} 项待处理</span>
        </div>
      </div>

      <div v-if="data" class="results-list">
        <div class="section-title">重复报销（{{ stats.duplicate }} 组）—— 点击查看两张发票详情</div>
        <div v-for="(d, i) in data.duplicateInvoices" :key="'d' + i" class="result-item clickable" @click="viewDuplicate(d)">
          <div class="result-header">
            <el-tag :type="d.suspected ? 'warning' : 'danger'" effect="dark" size="small">
              {{ d.suspected ? '疑似重复' : '重复发票' }}
            </el-tag>
            <span class="result-id mono">{{ d.invoiceCode }} / {{ d.invoiceNo }}</span>
            <span v-if="d.otherCodes?.length" class="result-meta">
              另含代码 {{ d.otherCodes.join(', ') }}
            </span>
            <span class="result-meta">涉及 {{ (d.claimIds || []).length }} 张单据</span>
            <el-tag
              v-if="aiVerdictFor(d, 'duplicate')?.verdict"
              :type="aiLabels[aiVerdictFor(d, 'duplicate').verdict]?.type || 'info'"
              size="small"
              effect="plain"
            >
              {{ aiLabels[aiVerdictFor(d, 'duplicate').verdict]?.label || aiVerdictFor(d, 'duplicate').verdict }}
            </el-tag>
            <el-icon class="chevron"><ArrowRight /></el-icon>
          </div>
          <div class="result-body">
            <p>单据：<span class="mono">{{ (d.claimIds || []).join(', ') }}</span></p>
          </div>
        </div>

        <div class="section-title">票面问题（{{ stats.total - stats.duplicate }} 项）—— 点击查看发票详情</div>
        <div v-for="(it, i) in data.invoiceIssues" :key="'i' + i" class="result-item clickable" @click="viewIssue(it)">
          <div class="result-header">
            <el-tag type="warning" effect="dark" size="small">{{ issueLabels[it.issue] || it.issue }}</el-tag>
            <span class="result-id mono">{{ it.invoiceId }}</span>
            <el-tag
              v-if="aiVerdictFor(it, 'issue')?.verdict"
              :type="aiLabels[aiVerdictFor(it, 'issue').verdict]?.type || 'info'"
              size="small"
              effect="plain"
            >
              {{ aiLabels[aiVerdictFor(it, 'issue').verdict]?.label || aiVerdictFor(it, 'issue').verdict }}
            </el-tag>
            <el-icon class="chevron"><ArrowRight /></el-icon>
          </div>
        </div>

        <div class="section-title" style="margin-top: 18px">
          AI 全量巡检（{{ aiScan?.flaggedCount || 0 }} 项疑似）—— 点击查看发票详情
        </div>
        <div v-if="aiScan?.flagged?.length" class="ai-scan-list">
          <div v-for="(f, i) in aiScan.flagged" :key="'s' + i" class="result-item clickable" @click="viewAiFlag(f)">
            <div class="result-header">
              <el-tag :type="scanTypeMeta[f.type]?.type || 'info'" effect="dark" size="small">
                {{ scanTypeMeta[f.type]?.label || f.type }}
              </el-tag>
              <span class="result-id mono">{{ f.invoiceId }}</span>
              <span class="result-meta">置信度 {{ Math.round((f.confidence || 0) * 100) }}%</span>
              <el-icon class="chevron"><ArrowRight /></el-icon>
            </div>
            <div class="result-body">
              <p>{{ f.reason }}</p>
            </div>
          </div>
        </div>
        <div v-else-if="aiScan" class="ai-scan-empty">本次巡检未发现疑似异常</div>

        <div v-if="data?.supplierProfiles?.length" class="section-title" style="margin-top: 18px">
          供应商画像（{{ data.supplierProfiles.length }} 家疑似）—— 点击查看开票明细
        </div>
        <div v-if="data?.supplierProfiles?.length" class="ai-scan-list">
          <div
            v-for="(prof, i) in data.supplierProfiles"
            :key="'p' + i"
            class="result-item clickable"
            @click="viewSupplierProfile(prof)"
          >
            <div class="result-header">
              <el-tag type="danger" effect="dark" size="small">疑似虚开</el-tag>
              <span class="result-id">{{ prof.sellerName }}</span>
              <span class="result-meta">{{ prof.invoiceCount }} 张发票</span>
              <span class="result-meta">
                低额占比 {{ Math.round((prof.lowRatio || 0) * 100) }}% · 连号 {{ prof.consecutiveRuns }} 段
              </span>
              <el-icon class="chevron"><ArrowRight /></el-icon>
            </div>
            <div class="result-body">
              <p>{{ prof.basis }}</p>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="empty-state">
        <el-icon :size="48"><CircleCheck /></el-icon>
        <p>点击「开始全量扫描」执行发票台账稽核</p>
      </div>
    </div>

    <el-dialog v-model="detailVisible" :title="detailTitle" width="900px">
      <div v-if="detailBasis" class="basis-box">
        <el-icon><DocumentChecked /></el-icon>
        <div>
          <div class="basis-label">判断依据</div>
          <div class="basis-text">{{ detailBasis }}</div>
        </div>
      </div>
      <div v-if="detailAi" :class="['ai-box', detailAi.verdict?.toLowerCase()]">
        <el-icon><MagicStick /></el-icon>
        <div>
          <div class="basis-label">
            AI 复核意见：{{ aiLabels[detailAi.verdict]?.label || detailAi.verdict }}
            <span class="ai-conf">置信度 {{ Math.round((detailAi.confidence || 0) * 100) }}%</span>
            <el-tag size="small" effect="plain" class="ai-conf">Skill: m3-ai-review</el-tag>
          </div>
          <div class="basis-text">{{ (detailAi.reasons || []).join('；') }}</div>
        </div>
      </div>
      <div class="invoice-detail-list">
        <div v-for="(inv, i) in detailInvoices" :key="i" class="invoice-detail-card">
          <div class="invoice-left">
            <div class="inv-row"><span class="inv-label">单据</span><span class="inv-value mono">{{ inv.claimNo }}（{{ inv.claimId }}）</span></div>
            <div class="inv-row"><span class="inv-label">费用行</span><span class="inv-value mono">第 {{ inv.lineNo }} 行</span></div>
            <div class="inv-row"><span class="inv-label">发票代码/号码</span><span class="inv-value mono">{{ inv.invoiceCode }} / {{ inv.invoiceNo }}</span></div>
            <div class="inv-row"><span class="inv-label">开票日期</span><span class="inv-value">{{ inv.issuedOn }}</span></div>
            <div class="inv-row"><span class="inv-label">购方名称</span><span class="inv-value">{{ inv.buyerName }}</span></div>
            <div class="inv-row"><span class="inv-label">购方税号</span><span class="inv-value mono">{{ inv.buyerTaxNo }}</span></div>
            <div class="inv-row"><span class="inv-label">销方名称</span><span class="inv-value">{{ inv.sellerName }}</span></div>
            <div class="inv-row"><span class="inv-label">金额</span><span class="inv-value mono">¥{{ yuan(inv.totalFen) }}</span></div>
            <div class="inv-row"><span class="inv-label">税率</span><span class="inv-value mono">{{ inv.taxRate != null ? (inv.taxRate * 100) + '%' : '-' }}</span></div>
          </div>
          <div class="invoice-right">
            <template v-if="inv.attachmentId && inv.migrated !== false">
              <img
                :src="`/api/erp/attachments/${inv.attachmentId}/content`"
                :alt="inv.invoiceNo"
                loading="lazy"
                class="invoice-img"
                @click="openImg(inv.attachmentId)"
              />
              <span class="img-hint">点击放大</span>
            </template>
            <div v-else class="no-img">
              {{ inv.attachmentId ? '该票据未迁移（旧档案系统），无影像可查' : '无票据影像' }}
            </div>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.m3-anomaly-page { max-width: 1400px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
.header-actions { display: flex; gap: 10px; }
.btn-secondary {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 10px 18px;
  background: rgba(10, 143, 117, 0.08);
  border: 1px solid rgba(10, 143, 117, 0.3);
  border-radius: 8px;
  color: var(--brand);
  font-family: var(--font-body);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}
.btn-secondary:hover { background: rgba(10, 143, 117, 0.14); }
.btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }
.page-title { font-family: var(--font-display); font-size: 28px; font-weight: 700; color: var(--text-primary); margin: 0; }
.page-subtitle { font-size: 14px; color: var(--text-muted); margin-top: 4px; }
.stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
.stat-card { padding: 24px; text-align: center; }
.stat-value { font-size: 36px; font-weight: 700; color: var(--brand); }
.stat-value.danger { color: var(--danger); }
.stat-value.warning { color: var(--warning); }
.stat-label { font-size: 13px; color: var(--text-muted); margin-top: 4px; }
.results-panel { padding: 0; overflow: hidden; }
.panel-header { display: flex; justify-content: space-between; align-items: center; padding: 20px 24px; border-bottom: 1px solid var(--glass-border); }
.panel-header h3 { font-family: var(--font-display); font-size: 15px; font-weight: 600; margin: 0; }
.panel-right { display: flex; align-items: center; gap: 10px; }
.result-count { font-family: var(--font-display); font-size: 13px; color: var(--brand); }
.cache-tag { font-size: 11px; color: var(--text-muted); background: var(--bg-tertiary); border: 1px solid var(--glass-border); border-radius: 4px; padding: 2px 8px; }
.results-list { padding: 8px 0; }
.section-title { padding: 14px 24px 6px; font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.result-item { padding: 14px 24px; border-bottom: 1px solid var(--glass-border); }
.result-item:last-child { border-bottom: none; }
.result-item.clickable { cursor: pointer; transition: background 0.2s; }
.result-item.clickable:hover { background: rgba(10, 143, 117, 0.04); }
.result-header { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.result-id { font-size: 12px; color: var(--text-muted); }
.result-meta { font-size: 12px; color: var(--text-secondary); }
.chevron { margin-left: auto; color: var(--text-muted); }
.result-body p { font-size: 14px; margin: 0; color: var(--text-primary); }
.empty-state { display: flex; flex-direction: column; align-items: center; padding: 60px 0; gap: 16px; color: var(--text-muted); }
.empty-state .el-icon { color: var(--success); opacity: 0.4; }
.empty-state p { margin: 0; font-size: 14px; }

.invoice-detail-list { display: flex; flex-direction: column; gap: 16px; max-height: 70vh; overflow: auto; }
.basis-box {
  display: flex;
  gap: 10px;
  padding: 12px 16px;
  margin-bottom: 16px;
  background: rgba(10, 143, 117, 0.06);
  border-left: 3px solid var(--brand);
  border-radius: 6px;
  color: var(--text-primary);
}
.basis-box .el-icon { color: var(--brand); font-size: 18px; margin-top: 2px; }
.basis-label { font-size: 12px; color: var(--text-muted); margin-bottom: 4px; }
.basis-text { font-size: 13px; line-height: 1.6; }
.ai-box { display: flex; gap: 10px; padding: 12px 16px; margin-bottom: 16px; border-radius: 6px; color: var(--text-primary); }
.ai-box .el-icon { font-size: 18px; margin-top: 2px; }
.ai-box.confirm { background: rgba(26, 147, 111, 0.08); border-left: 3px solid var(--success); }
.ai-box.confirm .el-icon { color: var(--success); }
.ai-box.doubt { background: rgba(245, 166, 35, 0.08); border-left: 3px solid var(--warning); }
.ai-box.doubt .el-icon { color: var(--warning); }
.ai-box.false_alarm { background: rgba(229, 72, 77, 0.08); border-left: 3px solid var(--danger); }
.ai-box.false_alarm .el-icon { color: var(--danger); }
.ai-conf { margin-left: 8px; color: var(--text-muted); }
.invoice-detail-card { display: flex; gap: 20px; padding: 18px; border: 1px solid var(--glass-border); border-radius: 8px; }
.invoice-left { flex: 1; display: flex; flex-direction: column; gap: 8px; }
.inv-row { display: flex; gap: 10px; font-size: 13px; }
.inv-label { width: 110px; color: var(--text-muted); flex-shrink: 0; }
.inv-value { color: var(--text-primary); }
.invoice-right { width: 320px; display: flex; flex-direction: column; align-items: center; gap: 6px; }
.invoice-img { max-width: 100%; max-height: 260px; object-fit: contain; border-radius: 6px; cursor: zoom-in; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
.img-hint { font-size: 11px; color: var(--text-muted); }
.no-img { width: 100%; height: 160px; display: flex; align-items: center; justify-content: center; background: var(--bg-tertiary); border-radius: 6px; color: var(--text-muted); font-size: 12px; }
.ai-scan-empty { padding: 12px 16px; color: var(--text-muted); font-size: 13px; }
</style>
