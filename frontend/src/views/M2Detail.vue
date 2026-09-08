<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuditStore } from '../stores/audit'
import { useConnectionStore } from '../stores/connection'
import api from '../api'
import StatusBadge from '../components/StatusBadge.vue'
import ReviewPanel from '../components/ReviewPanel.vue'

const route = useRoute()
const router = useRouter()
const auditStore = useAuditStore()
const connStore = useConnectionStore()

const claim = ref(null)
const companyRef = ref({ name: '', taxNo: '' })
const loading = ref(true)
const activeTab = ref('details')

const selectedInvoiceId = ref(null)
const ocrEditable = ref({})
const verified = ref(false)
const savingEdit = ref(false)

const systemFields = computed(() => {
  if (!claim.value || !selectedInvoice.value) return {}
  const inv = selectedInvoice.value
  return {
    buyerName: companyRef.value.name,
    buyerTaxNo: companyRef.value.taxNo,
    vendor: inv.vendor,
    amount: inv.amount.toFixed(2),
    date: inv.date,
    code: inv.code,
    category: inv.category,
  }
})

const ocrFields = computed(() => {
  const inv = selectedInvoice.value
  if (!inv) return {}
  const editable = { ...ocrEditable.value }
  if (!editable.buyerName) editable.buyerName = inv.ocrBuyerName || ''
  if (!editable.buyerTaxNo) editable.buyerTaxNo = inv.ocrBuyerTaxNo || ''
  if (!editable.vendor) editable.vendor = inv.ocr?.vendor || inv.vendor
  if (!editable.amount) editable.amount = inv.ocr?.amount?.toFixed(2) || inv.amount.toFixed(2)
  if (!editable.date) editable.date = inv.ocr?.date || inv.date
  if (!editable.code) editable.code = inv.ocr?.code || inv.code
  if (!editable.category) editable.category = inv.ocr?.category || inv.category
  return editable
})

const fieldDiffs = computed(() => {
  const diffs = {}
  const ocr = ocrFields.value
  const sys = systemFields.value
  if (!sys || Object.keys(sys).length === 0) return diffs
  for (const key of Object.keys(sys)) {
    const ocrVal = String(ocr[key] || '').trim()
    const sysVal = String(sys[key] || '').trim()
    // 购方信息：OCR 为空（如火车票无购方栏）不标差异
    if ((key === 'buyerName' || key === 'buyerTaxNo') && !ocrVal) {
      diffs[key] = false
      continue
    }
    diffs[key] = ocrVal !== sysVal
  }
  return diffs
})

const diffCount = computed(() => Object.values(fieldDiffs.value).filter(Boolean).length)

const selectedInvoice = computed(() => {
  if (!claim.value?.invoices) return null
  if (!selectedInvoiceId.value && claim.value.invoices.length) {
    return claim.value.invoices[0]
  }
  return claim.value.invoices.find(i => i.id === selectedInvoiceId.value)
})

function selectInvoice(id) {
  selectedInvoiceId.value = id
  verified.value = false
  const inv = claim.value?.invoices?.find(i => i.id === id)
  if (inv) {
    ocrEditable.value = {
      buyerName: inv.ocrBuyerName || '',
      buyerTaxNo: inv.ocrBuyerTaxNo || '',
      vendor: inv.ocr?.vendor || inv.vendor,
      amount: inv.ocr?.amount?.toFixed(2) || inv.amount.toFixed(2),
      date: inv.ocr?.date || inv.date,
      code: inv.ocr?.code || inv.code,
      category: inv.ocr?.category || inv.category,
    }
  }
}

function updateOcrField(key, value) {
  ocrEditable.value = { ...ocrEditable.value, [key]: value }
}

async function saveEdit() {
  savingEdit.value = true
  await new Promise(r => setTimeout(r, 600))
    if (claim.value && selectedInvoice.value) {
      const inv = claim.value.invoices.find(i => i.id === selectedInvoice.value.id)
      if (inv) {
        inv.ocr = {
          buyerName: ocrEditable.value.buyerName,
          buyerTaxNo: ocrEditable.value.buyerTaxNo,
          vendor: ocrEditable.value.vendor,
        amount: parseFloat(ocrEditable.value.amount),
        date: ocrEditable.value.date,
        code: ocrEditable.value.code,
        category: ocrEditable.value.category,
      }
    }
  }
  savingEdit.value = false
  ElMessage.success('修改已保存')
}

onMounted(async () => {
  const claimId = route.params.claimId
  if (!claimId) return
  loading.value = true
  try {
    // 拉取真实单据详情（ERP 开放平台）
    const detail = await api.get('/erp/claims/' + claimId, {
      params: { api_url: connStore.apiUrl, api_key: connStore.apiKey },
    })
    const auditResult = auditStore.auditResults.find(r => r.claimId === claimId)
    claim.value = {
      id: detail.id,
      claimNo: detail.claimNo,
      employeeName: detail.employeeName,
      department: detail.departmentName,
      totalAmount: (detail.totalFen || 0) / 100,
      currency: detail.currency || 'CNY',
      submitDate: (detail.submittedAt || '').replace('T', ' ').slice(0, 16),
      status: detail.status,
      auditResult: auditResult?.result || null,
      confidence: auditResult?.decisionStrength ?? auditResult?.confidence ?? null,
      aiReview: auditResult?.aiReview || null,
      invoices: (detail.lines || []).map(ln => {
        const inv = ln.invoice || {}
        const seller = inv.seller || {}
        const att = ln.attachment || {}
        return {
          id: inv.id || ln.id,
          date: inv.issuedOn || ln.occurredOn || '',
          vendor: seller.name || '',
          amount: (inv.totalFen != null ? inv.totalFen : ln.amountFen || 0) / 100,
          code: [inv.invoiceCode, inv.invoiceNo].filter(Boolean).join(' / '),
          category: ln.expenseType || '',
          sysBuyerName: (inv.buyer && inv.buyer.name) || '',
          sysBuyerTaxNo: (inv.buyer && inv.buyer.taxNo) || '',
          attachmentId: att.id || null,
          imgUrl: att.id ? `/api/erp/attachments/${att.id}/content` : null,
        }
      }),
      violations: (auditResult?.violations || []).map((code, i) => ({
        id: 'V' + i,
        rule: code,
        description: (auditResult.reasons && auditResult.reasons[i]) || code,
        severity: 'MEDIUM',
      })),
      aiAdvice: {
        result: auditResult?.result || null,
        summary: auditResult
          ? `AI 建议：${auditResult.result}，违规项 ${auditResult.violations.length} 项`
          : '尚未执行 AI 审核，请在列表页批量审核后查看。',
        confidence: auditResult?.decisionStrength ?? auditResult?.confidence ?? 0,
        suggestions: [],
      },
    }
    // 拉取 OCR 购方抬头/税号（本地缓存）与公司真实信息
    try {
      const ocrResp = await api.get('/erp/claims/' + claimId + '/ocr-fields', {
        params: { api_url: connStore.apiUrl, api_key: connStore.apiKey },
      })
      companyRef.value = { name: ocrResp.companyName, taxNo: ocrResp.companyTaxNo }
      claim.value.invoices = (claim.value.invoices || []).map(inv => {
        const f = (ocrResp.fields || {})[inv.attachmentId] || {}
        return { ...inv, ocrBuyerName: f.buyerName || '', ocrBuyerTaxNo: f.buyerTaxNo || '' }
      })
    } catch (e) {
      console.warn('OCR 字段拉取失败', e)
    }
    if (claim.value.invoices.length) {
      selectInvoice(claim.value.invoices[0].id)
    }
  } finally {
    loading.value = false
  }
})

const totalAmount = computed(() => {
  if (!claim.value) return 0
  return claim.value.invoices?.reduce((sum, i) => sum + i.amount, 0) || 0
})

const severityClass = (level) => {
  // 违规项统一用红色展示
  return 'danger'
}

const verdictMap = {
  APPROVE: '建议通过',
  REJECT: '建议驳回',
  FLAG: '存疑复核',
}

function verdictLabel(v) {
  return verdictMap[v] || v || '未审核'
}

const investigationConclusionMap = {
  maintain_rules: '维持规则结论',
  support_flag: '支持存疑待人工',
  suggest_approve: '建议放行',
  suggest_reject: '建议驳回',
}

function investigationLabel(inv) {
  if (!inv) return ''
  const base = investigationConclusionMap[inv.conclusion] || inv.conclusion || '调查完成'
  return inv.degraded ? `${base}（已降级）` : base
}

const violationLabels = {
  OVER_STANDARD_HOTEL: '住宿超标',
  OVER_STANDARD_MEAL: '伙食超标',
  OVER_STANDARD_CITY_TRANSPORT: '市内交通超标',
  OVER_STANDARD_TRANSPORT_CLASS: '舱位超标',
  INVOICE_TITLE_MISMATCH: '发票抬头错误',
  INVOICE_TAXNO_MISMATCH: '发票税号错误',
  AMOUNT_MISMATCH: '金额不一致',
  DUPLICATE_INVOICE: '重复报销',
  MISSING_APPROVAL_OVERTIME_TAXI: '加班打车缺审批',
  MISSING_ATTACHMENT: '缺少票据附件',
  ACCOUNT_MISMATCH: '科目归集错误',
}

function ruleLabel(rule) {
  return violationLabels[rule] || rule
}

async function copyReasons() {
  const c = claim.value
  if (!c) return
  const lines = []
  lines.push(`报销单 ${c.claimNo || c.id} 审核结论：${verdictLabel(c.auditResult)}`)
  lines.push(`依据：《费用报销管理办法 V3.2》`)
  for (const v of c.violations || []) {
    lines.push(`- [${ruleLabel(v.rule)}] ${v.description}`)
  }
  if (c.aiReview?.reasons?.length) {
    lines.push('AI 复核意见：')
    for (const r of c.aiReview.reasons) lines.push(`- ${r}`)
  }
  try {
    await navigator.clipboard.writeText(lines.join('\n'))
    ElMessage.success('退单理由已复制，可直接发给报销人')
  } catch (e) {
    ElMessage.error('复制失败，请手动选择文本复制')
  }
}

const approvalSuggestion = computed(() => {
  const r = claim.value?.auditResult
  if (r === 'APPROVE') return '可直接放行：未发现违规项，证据充分，进入付款环节。'
  if (r === 'REJECT') return '建议驳回：违规项及理由见「规则匹配结果」，可直接反馈报销人补充或更正。'
  if (r === 'FLAG') return '建议人工复核：存在规则/AI 分歧或证据不足，人工确认后再决定是否放行。'
  return '尚未执行 AI 审核，请先在列表页批量审核。'
})

function goBack() {
  router.push('/m2')
}

function openImage() {
  if (selectedInvoice.value?.imgUrl) {
    window.open(selectedInvoice.value.imgUrl, '_blank')
  }
}

async function handleReviewSubmit(payload) {
  if (!payload || !payload.claimId) return
  try {
    // 图管线人工终审（AGENT_HUMAN_GATE=1）：该单在待终审清单中 → resume 恢复 LangGraph
    const pend = await api.get('/m2/pending-human').catch(() => null)
    const pending = (pend?.pending || []).find(p => p.claimId === payload.claimId)
    if (pending) {
      await api.post(`/m2/human-gate/run/${pending.workflowRunId}/resume`, {
        decision: payload.decision,
        comment: payload.comment || '',
        expectedRevision: pending.revision ?? 0,
        apiUrl: connStore.apiUrl,
        apiKey: connStore.apiKey,
      })
      ElMessage.success('人工终审决定已恢复图管线并回写 ERP')
      return
    }
    const aiResult = claim.value?.auditResult
    await auditStore.submitReview(payload.claimId, {
      decision: payload.decision,
      comment: payload.comment,
      aiResult,
      aiViolations: (claim.value?.violations || []).map(v => v.rule),
      aiReasons: (claim.value?.violations || []).map(v => v.description),
      aiConfidence: claim.value?.confidence ?? null,
    })
    ElMessage.success('审核意见已回写 ERP（AI 只给意见，状态由人工操作流转）')
  } catch (e) {
    const detail = e?.response?.data?.detail
    const msg = typeof detail === 'string' ? detail : (detail ? JSON.stringify(detail) : (e?.message || '请求失败'))
    ElMessage.error('回写失败: ' + msg)
  }
}

const fieldLabels = {
  buyerName: '购方名称',
  buyerTaxNo: '购方税号',
  vendor: '销售方/供应商',
  amount: '金额',
  date: '开票日期',
  code: '发票代码',
  category: '费用类型',
}
</script>

<template>
  <div class="m2-detail">
    <div class="page-nav">
      <button class="btn-ghost back-btn" @click="goBack">
        <el-icon><ArrowLeft /></el-icon>
        <span>返回列表</span>
      </button>
    </div>

    <div v-if="loading" class="loading-state">
      <el-icon :size="48" class="spin-icon"><Loading /></el-icon>
      <span>加载审核详情中...</span>
    </div>

    <template v-else-if="claim">
      <header class="detail-header glass-card">
        <div class="header-top">
          <div class="claim-identity">
            <h1 class="claim-no mono">#{{ claim.claimNo }}</h1>
            <StatusBadge :status="claim.auditResult" />
          </div>
          <div class="amount-block">
            <span class="amount-label">报销金额</span>
            <span class="amount-value">¥{{ totalAmount.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</span>
          </div>
        </div>

        <div class="info-grid">
          <div class="info-item">
            <span class="info-label">申请人</span>
            <span class="info-value">{{ claim.employeeName }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">部门</span>
            <span class="info-value">{{ claim.department }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">提交时间</span>
            <span class="info-value">{{ claim.submitDate }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">币种</span>
            <span class="info-value">{{ claim.currency }}</span>
          </div>
        </div>
      </header>

      <div class="detail-tabs">
        <button
          v-for="tab in [
            { key: 'details', label: '费用明细' },
            { key: 'result', label: `审核结果 (${claim.violations?.length || 0})` },
            { key: 'review', label: '人工复核' },
          ]"
          :key="tab.key"
          :class="['tab-btn', { active: activeTab === tab.key }]"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>

      <div class="tab-content">
        <div v-if="activeTab === 'details'" class="compare-container">
          <div class="invoice-tabs-bar glass-card">
            <button
              v-for="inv in claim.invoices"
              :key="inv.id"
              :class="['inv-tab', { active: selectedInvoiceId === inv.id }]"
              @click="selectInvoice(inv.id)"
            >
              <span class="inv-tab-type">{{ inv.category }}</span>
              <span class="inv-tab-vendor">{{ inv.vendor }}</span>
              <span class="inv-tab-amount mono">¥{{ inv.amount.toLocaleString() }}</span>
            </button>
          </div>

          <div v-if="selectedInvoice" class="three-column-layout glass-card">
            <div class="col col-image">
              <div class="col-header">
                <el-icon><Picture /></el-icon>
                <span>票据图片</span>
              </div>
              <div v-if="selectedInvoice.imgUrl" class="invoice-image">
                <img
                  :src="selectedInvoice.imgUrl"
                  :alt="selectedInvoice.vendor"
                  loading="lazy"
                  @click="openImage"
                />
                <div class="image-hint">
                  <el-icon><ZoomIn /></el-icon>
                  <span>点击查看大图</span>
                </div>
              </div>
              <div v-else class="image-placeholder">
                <el-icon :size="48"><Document /></el-icon>
                <p>{{ selectedInvoice.vendor }} - {{ selectedInvoice.category }}</p>
                <span>该费用行无票据影像</span>
              </div>
            </div>

            <div class="col col-ocr">
              <div class="col-header">
                <el-icon><Edit /></el-icon>
                <span>OCR 识别结果</span>
                <el-tag size="small" type="warning" effect="dark">可编辑</el-tag>
              </div>
              <div class="fields-list">
                <div
                  v-for="key in Object.keys(fieldLabels)"
                  :key="key"
                  :class="['field-row', { diff: fieldDiffs[key] }]"
                >
                  <label class="field-label">{{ fieldLabels[key] }}</label>
                  <el-input
                    :model-value="ocrFields[key]"
                    @update:model-value="(v) => updateOcrField(key, v)"
                    size="default"
                  />
                  <el-icon v-if="fieldDiffs[key]" class="diff-icon"><Warning /></el-icon>
                </div>
              </div>
              <div
                v-if="!ocrFields.buyerName && selectedInvoice.sysBuyerName && selectedInvoice.sysBuyerName !== companyRef.name"
                class="ocr-fallback-note"
              >
                <el-icon><InfoFilled /></el-icon>
                <span>票面无购方栏，抬头/税号按系统录入判定（见右侧「系统录入」）</span>
              </div>
              <div v-if="diffCount" class="diff-summary">
                <el-icon><Warning /></el-icon>
                <span>检测到 <strong>{{ diffCount }}</strong> 处差异</span>
              </div>
            </div>

            <div class="col col-system">
              <div class="col-header">
                <el-icon><Lock /></el-icon>
                <span>系统录入字段</span>
                <el-tag size="small" type="info" effect="plain">只读</el-tag>
              </div>
              <div class="fields-list">
                <div
                  v-for="key in Object.keys(fieldLabels)"
                  :key="key"
                  :class="['field-row', { diff: fieldDiffs[key] }]"
                >
                  <label class="field-label">{{ fieldLabels[key] }}</label>
                  <div class="field-value mono">{{ systemFields[key] }}</div>
                  <span
                    v-if="key === 'buyerName' && selectedInvoice.sysBuyerName && selectedInvoice.sysBuyerName !== companyRef.name"
                    class="sys-entry-note"
                  >
                    系统录入：{{ selectedInvoice.sysBuyerName }}
                  </span>
                  <span v-if="fieldDiffs[key]" class="diff-badge">不一致</span>
                </div>
              </div>
              <div class="match-summary">
                <span v-if="diffCount === 0" class="match-ok">
                  <el-icon><CircleCheck /></el-icon>
                  <span>所有字段一致</span>
                </span>
                <span v-else class="match-warn">
                  <el-icon><Warning /></el-icon>
                  <span>{{ diffCount }} 处需核对</span>
                </span>
              </div>
            </div>
          </div>

          <div v-if="selectedInvoice" class="compare-actions glass-card">
            <div class="actions-left">
              <el-checkbox v-model="verified" active-color="#0A8F75">
                <span class="checkbox-label">标记为已核对</span>
              </el-checkbox>
              <span v-if="verified" class="verified-badge">
                <el-icon><CircleCheck /></el-icon>
                <span>已核对</span>
              </span>
            </div>
            <div class="actions-right">
              <span v-if="diffCount" class="diff-warn">
                <el-icon><Warning /></el-icon>
                <span>存在 {{ diffCount }} 处差异未处理</span>
              </span>
              <button
                class="btn-primary"
                :disabled="savingEdit"
                @click="saveEdit"
              >
                <el-icon v-if="!savingEdit"><Check /></el-icon>
                <span style="margin-left: 6px">{{ savingEdit ? '保存中...' : '保存修改' }}</span>
              </button>
            </div>
          </div>
        </div>

        <div v-else-if="activeTab === 'result'" class="result-panel">
          <!-- 1. 规则匹配结果 -->
          <div class="res-block glass-card">
            <div class="res-head">
              <h3>规则匹配结果</h3>
              <el-tag type="info" size="small" effect="plain">依据《费用报销管理办法 V3.2》</el-tag>
              <span class="res-verdict" :class="'v-' + (claim.auditResult || 'none').toLowerCase()">
                {{ verdictLabel(claim.auditResult) }}
              </span>
              <span v-if="claim.confidence != null" class="res-conf">规则决策强度 {{ Math.round(claim.confidence * 100) }}%</span>
            </div>
            <div v-if="claim.violations?.length" class="violation-list">
              <div v-for="v in claim.violations" :key="v.id" class="violation-item">
                <div :class="['violation-indicator', v.severity.toLowerCase()]"></div>
                <div class="violation-content">
                  <div class="violation-header">
                    <span class="rule-label">{{ ruleLabel(v.rule) }}</span>
                    <span class="rule-code mono">{{ v.rule }}</span>
                    <el-tag type="danger" size="small" effect="dark">{{ v.severity }}</el-tag>
                  </div>
                  <p class="violation-desc">{{ v.description }}</p>
                </div>
              </div>
              <button class="btn-secondary copy-btn" @click="copyReasons">
                <el-icon><CopyDocument /></el-icon>
                <span style="margin-left: 4px">复制退单理由</span>
              </button>
            </div>
            <div v-else class="res-empty">
              <el-icon :size="18"><CircleCheck /></el-icon>
              <span>未检测到违规项</span>
            </div>
          </div>

          <!-- 2. AI 审核结果 -->
          <div class="res-block glass-card">
            <div class="res-head">
              <h3>AI 审核结果</h3>
              <span
                v-if="claim.aiReview?.result"
                class="res-verdict"
                :class="'v-' + claim.aiReview.result.toLowerCase()"
              >
                {{ verdictLabel(claim.aiReview.result) }}
              </span>
              <el-tag
                v-if="claim.aiReview?.agreeWithRules !== undefined"
                :type="claim.aiReview.agreeWithRules ? 'success' : 'warning'"
                size="small"
                effect="plain"
              >
                {{ claim.aiReview.agreeWithRules ? '与规则一致' : '与规则分歧' }}
              </el-tag>
            </div>
            <div v-if="claim.aiReview?.reasons?.length" class="ai-reasons">
              <p v-for="(r, i) in claim.aiReview.reasons" :key="i" class="ai-reason">{{ r }}</p>
              <div v-if="claim.aiReview.confidence != null" class="res-conf">AI 置信度 {{ Math.round(claim.aiReview.confidence * 100) }}%</div>
            </div>
            <div v-if="claim.aiReview?.investigation" class="investigation">
              <div class="invest-head">
                <span class="invest-title">调查 Agent</span>
                <el-tag size="small" effect="plain" type="info">
                  {{ investigationLabel(claim.aiReview.investigation) }}
                </el-tag>
                <span class="invest-meta mono">
                  {{ claim.aiReview.investigation.steps || 0 }} 步 /
                  {{ claim.aiReview.investigation.tool_calls || 0 }} 次工具调用
                </span>
              </div>
              <p v-if="claim.aiReview.investigation.summary" class="invest-summary">
                {{ claim.aiReview.investigation.summary }}
              </p>
              <ul v-if="claim.aiReview.investigation.evidence?.length" class="invest-evidence">
                <li v-for="(ev, i) in claim.aiReview.investigation.evidence" :key="i">
                  <span class="mono">{{ ev.tool }}</span>
                  <span class="ev-finding">{{ ev.finding }}</span>
                  <span v-if="ev.ref" class="ev-ref">{{ ev.ref }}</span>
                  <el-tag
                    v-if="ev.grounded !== null && ev.grounded !== undefined"
                    :type="ev.grounded ? 'success' : 'danger'"
                    size="small"
                    effect="plain"
                  >
                    {{ ev.grounded ? '已溯源' : '未溯源' }}
                  </el-tag>
                </li>
              </ul>
            </div>
            <div v-else class="res-empty">
              <el-icon :size="18"><MagicStick /></el-icon>
              <span>未启用 AI 复核或暂无结果（可在「系统设置」开启后重新审核）</span>
            </div>
          </div>

          <!-- 3. 审批建议 -->
          <div class="res-block glass-card">
            <div class="res-head">
              <h3>审批建议</h3>
            </div>
            <div class="approval-suggestion" :class="'s-' + (claim.auditResult || 'none').toLowerCase()">
              <el-icon :size="20"><InfoFilled /></el-icon>
              <span>{{ approvalSuggestion }}</span>
            </div>
          </div>
        </div>

        <ReviewPanel
          v-else-if="activeTab === 'review'"
          :claim="claim"
          @submit="handleReviewSubmit"
        />
      </div>
    </template>
  </div>
</template>

<style scoped>
.m2-detail {
  max-width: 1400px;
  margin: 0 auto;
}

.page-nav {
  margin-bottom: 16px;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 0;
  gap: 16px;
  color: var(--text-muted);
  font-family: var(--font-display);
}

.spin-icon {
  animation: spin 1s linear infinite;
  color: var(--brand);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.detail-header {
  padding: 28px 32px;
  margin-bottom: 20px;
}

.header-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  flex-wrap: wrap;
  gap: 20px;
}

.claim-identity {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.claim-no {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 700;
  margin: 0;
}

.amount-block {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.amount-label {
  font-size: 12px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 1px;
}

.amount-value {
  font-family: var(--font-display);
  font-size: 32px;
  font-weight: 700;
  color: var(--brand);
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px 32px;
  padding-top: 20px;
  border-top: 1px solid var(--glass-border);
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-label {
  font-size: 12px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.info-value {
  font-family: var(--font-display);
  font-size: 14px;
  color: var(--text-primary);
}

.detail-tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--glass-border);
  margin-bottom: 20px;
}

.tab-btn {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 12px 20px;
  color: var(--text-secondary);
  font-family: var(--font-body);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  margin-bottom: -1px;
}

.tab-btn:hover {
  color: var(--text-primary);
}

.tab-btn.active {
  color: var(--brand);
  border-bottom-color: var(--brand);
}

.tab-content {
  min-height: 400px;
}

.compare-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.invoice-tabs-bar {
  display: flex;
  gap: 8px;
  padding: 12px;
  overflow-x: auto;
}

.inv-tab {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: var(--bg-tertiary);
  border: 1px solid var(--glass-border);
  border-radius: var(--border-radius-sm);
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
  font-family: var(--font-body);
  color: var(--text-secondary);
}

.inv-tab:hover {
  border-color: var(--brand);
  color: var(--text-primary);
}

.inv-tab.active {
  border-color: var(--brand);
  background: rgba(10, 143, 117, 0.06);
  color: var(--text-primary);
}

.inv-tab-type {
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  background: rgba(10, 143, 117, 0.15);
  border-radius: 4px;
  color: var(--brand);
}

.inv-tab-vendor {
  font-size: 13px;
}

.inv-tab-amount {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.three-column-layout {
  display: grid;
  grid-template-columns: 1fr 1.2fr 1.2fr;
  gap: 0;
  overflow: hidden;
}

.col {
  display: flex;
  flex-direction: column;
  padding: 20px;
  min-height: 420px;
}

.col + .col {
  border-left: 1px solid var(--glass-border);
}

.col-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--glass-border);
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 14px;
}

.col-header .el-icon {
  color: var(--brand);
}

.col-system .col-header .el-icon {
  color: var(--text-muted);
}

.image-placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: #FAFBFC;
  border-radius: var(--border-radius-sm);
  border: 2px dashed #E5E8EC;
  color: var(--text-muted);
  cursor: zoom-in;
  transition: all 0.2s ease;
}

.image-placeholder:hover {
  border-color: var(--brand);
  background: rgba(10, 143, 117, 0.04);
}

.image-placeholder .el-icon {
  color: var(--brand);
  opacity: 0.4;
}

.image-placeholder p {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
}

.image-placeholder span {
  font-size: 12px;
}

.invoice-image {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 240px;
  background: var(--bg-tertiary);
  border-radius: 8px;
  padding: 12px;
}

.invoice-image img {
  max-width: 100%;
  max-height: 360px;
  object-fit: contain;
  cursor: zoom-in;
  border-radius: 6px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}

.ocr-fallback-note {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 10px;
  padding: 8px 10px;
  background: rgba(230, 162, 60, 0.08);
  border-left: 3px solid var(--warning);
  border-radius: 4px;
  color: var(--warning);
  font-size: 12px;
  line-height: 1.5;
}

.sys-entry-note {
  grid-column: 1 / -1;
  font-size: 11px;
  color: var(--warning);
  background: rgba(230, 162, 60, 0.08);
  border-radius: 4px;
  padding: 3px 8px;
  margin-top: 2px;
}

.image-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 12px;
  padding: 4px 12px;
  background: rgba(10, 143, 117, 0.1);
  border-radius: 4px;
  color: var(--brand);
  font-size: 12px;
}

.fields-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  flex: 1;
}

.field-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  position: relative;
  padding: 10px 12px;
  border-radius: var(--border-radius-sm);
  border: 1px solid transparent;
  transition: all 0.2s ease;
}

.field-row.diff {
  background: rgba(245, 166, 35, 0.06);
  border-color: rgba(245, 166, 35, 0.2);
}

.field-label {
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.diff-icon {
  position: absolute;
  top: 12px;
  right: 12px;
  color: var(--warning);
  font-size: 14px;
}

.field-value {
  padding: 8px 12px;
  background: var(--bg-tertiary);
  border-radius: 6px;
  font-size: 14px;
  color: var(--text-primary);
  min-height: 36px;
  display: flex;
  align-items: center;
}

.field-row.diff .field-value {
  color: var(--warning);
  font-weight: 600;
}

.diff-badge {
  position: absolute;
  top: 10px;
  right: 10px;
  font-size: 11px;
  padding: 2px 8px;
  background: var(--warning);
  color: #FFFFFF;
  border-radius: 4px;
  font-weight: 600;
}

.diff-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 10px 14px;
  background: rgba(245, 166, 35, 0.1);
  border: 1px solid rgba(245, 166, 35, 0.25);
  border-radius: var(--border-radius-sm);
  font-size: 13px;
  color: var(--warning);
}

.diff-summary strong {
  font-size: 16px;
}

.match-summary {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: var(--border-radius-sm);
  font-size: 13px;
}

.match-ok {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--success);
  background: rgba(26, 147, 111, 0.08);
}

.match-warn {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--warning);
  background: rgba(245, 166, 35, 0.08);
}

.compare-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  flex-wrap: wrap;
  gap: 12px;
}

.actions-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.checkbox-label {
  font-size: 14px;
  color: var(--text-primary);
}

.verified-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: rgba(26, 147, 111, 0.1);
  color: var(--success);
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
}

.actions-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.diff-warn {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--warning);
}

.violations-panel {
  padding: 0;
  overflow: hidden;
}

.result-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.res-block {
  padding: 20px 24px;
}

.res-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.res-head h3 {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 600;
  margin: 0;
}

.res-verdict {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 6px;
}

.res-verdict.v-approve { background: rgba(26, 147, 111, 0.1); color: var(--success); }
.res-verdict.v-reject { background: rgba(229, 72, 77, 0.1); color: var(--danger); }
.res-verdict.v-flag { background: rgba(245, 166, 35, 0.12); color: var(--warning); }
.res-verdict.v-none { background: var(--bg-tertiary); color: var(--text-muted); }

.res-conf {
  margin-left: auto;
  font-family: var(--font-display);
  font-size: 12px;
  color: var(--text-muted);
}

.ai-reasons {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.investigation {
  margin-top: 12px;
  padding: 12px 14px;
  background: rgba(10, 143, 117, 0.04);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.invest-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.invest-title {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.invest-meta {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-muted);
}

.invest-summary {
  margin: 8px 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.invest-evidence {
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.invest-evidence li {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.invest-evidence .ev-finding { flex: 1; }
.invest-evidence .ev-ref { color: var(--text-muted); }

.ai-reason {
  margin: 0;
  padding: 10px 14px;
  background: rgba(10, 143, 117, 0.05);
  border-left: 3px solid var(--brand);
  border-radius: 4px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
}

.res-empty {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 13px;
}

.approval-suggestion {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.6;
}

.approval-suggestion.s-approve { background: rgba(26, 147, 111, 0.08); color: var(--success); }
.approval-suggestion.s-reject { background: rgba(229, 72, 77, 0.08); color: var(--danger); }
.approval-suggestion.s-flag { background: rgba(245, 166, 35, 0.1); color: var(--warning); }
.approval-suggestion.s-none { background: var(--bg-tertiary); color: var(--text-muted); }

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid var(--glass-border);
}

.panel-header h3 {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 600;
  margin: 0;
}

.violation-count {
  font-family: var(--font-display);
  font-size: 13px;
  color: var(--text-muted);
}

.violation-list {
  padding: 8px 0;
}

.violation-item {
  display: flex;
  gap: 16px;
  padding: 16px 24px;
  border-bottom: 1px solid var(--glass-border);
  transition: background 0.2s ease;
}

.violation-item:hover {
  background: rgba(10, 143, 117, 0.02);
}

.violation-item:last-child {
  border-bottom: none;
}

.violation-indicator {
  width: 4px;
  border-radius: 2px;
  flex-shrink: 0;
  background: var(--brand);
  opacity: 0.4;
}

.violation-indicator.high { opacity: 1; }
.violation-indicator.medium { opacity: 0.6; }
.violation-indicator.low { opacity: 0.3; }

.violation-content {
  flex: 1;
}

.violation-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.rule-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--danger, #e5484d);
}

.rule-code {
  font-size: 13px;
  font-weight: 600;
}

.copy-btn {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  margin-top: 8px;
  border: 1px solid rgba(10, 143, 117, 0.3);
  border-radius: 6px;
  background: rgba(10, 143, 117, 0.08);
  color: var(--brand);
  font-size: 13px;
  cursor: pointer;
}

.violation-desc {
  font-size: 14px;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.violation-amount {
  font-family: var(--font-display);
  font-size: 12px;
  color: var(--text-muted);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 0;
  gap: 16px;
  color: var(--text-muted);
}

.empty-state p {
  margin: 0;
  font-size: 14px;
}
</style>
