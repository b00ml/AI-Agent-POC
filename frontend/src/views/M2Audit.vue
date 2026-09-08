<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useConnectionStore } from '../stores/connection'
import { useAuditStore } from '../stores/audit'
import StatsCards from '../components/StatsCards.vue'
import ClaimTable from '../components/ClaimTable.vue'

const router = useRouter()
const connStore = useConnectionStore()
const auditStore = useAuditStore()

const showConnectDialog = ref(false)
const auditing = ref(false)
const auditProgress = ref({ processed: 0, total: 0, phase: '' })
const writeBackToErp = ref(false)
const statusFilter = ref('PENDING')
const keyword = ref('')

const displayClaims = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return auditStore.claims
  return auditStore.claims.filter(c =>
    (c.claimNo || '').toLowerCase().includes(kw) ||
    (c.title || '').toLowerCase().includes(kw) ||
    (c.employeeName || '').toLowerCase().includes(kw)
  )
})

const phaseLabel = computed(() => {
  if (auditProgress.value.phase === 'ai') return 'AI复核'
  if (auditProgress.value.phase === 'rules') return '规则审核'
  return ''
})

onMounted(async () => {
  if (!connStore.connected) {
    showConnectDialog.value = true
  } else {
    await loadData()
  }
})

async function loadData() {
  await auditStore.loadClaims({ page: 1, pageSize: 30, status: statusFilter.value })
}

async function handleConnect() {
  await connStore.connect()
  if (connStore.connected) {
    showConnectDialog.value = false
    await loadData()
  }
}

async function runAudit() {
  if (auditStore.selectedIds.length === 0) return
  auditing.value = true
  auditProgress.value = { processed: 0, total: auditStore.selectedIds.length }
  try {
    await auditStore.runAudit(
      auditStore.selectedIds,
      p => { auditProgress.value = p },
      writeBackToErp.value,
    )
    await loadData()
  } finally {
    auditing.value = false
  }
}

function viewDetail(claimId) {
  router.push(`/m2/${claimId}`)
}

function handleSelectionChange(ids) {
  auditStore.selectClaims(ids)
}

async function handleQuery() {
  await auditStore.loadClaims({ page: 1, pageSize: 30, status: statusFilter.value })
}

async function handleReset() {
  statusFilter.value = 'ALL'
  keyword.value = ''
  await auditStore.loadClaims({ page: 1, pageSize: 30, status: 'ALL' })
}

async function handlePageChange(page) {
  await auditStore.loadClaims({ page, pageSize: 30, status: statusFilter.value })
}
</script>

<template>
  <div class="m2-audit-page">
    <header class="page-header">
      <div class="header-left">
        <h1 class="page-title">M2 合规审核</h1>
        <p class="page-subtitle">差旅报销 AI 自动审核 · 10 种违规检测</p>
      </div>
      <div class="header-right">
        <button v-if="!connStore.connected" class="btn-primary" @click="showConnectDialog = true">
          <el-icon><Connection /></el-icon>
          <span style="margin-left: 6px">连接 ERP</span>
        </button>
        <template v-else>
          <el-checkbox
            v-model="writeBackToErp"
            :disabled="auditing"
            class="writeback-toggle"
            title="审核完成后将 AI 建议与审核意见写入 ERP（不改变单据状态）"
          >
            写回 ERP
          </el-checkbox>
          <button
            class="btn-primary"
            :disabled="auditing || auditStore.selectedIds.length === 0"
            @click="runAudit"
          >
            <el-icon v-if="!auditing"><VideoPlay /></el-icon>
            <span style="margin-left: 6px">
                {{ auditing ? `审核中${phaseLabel ? ' ' + phaseLabel : ''} ${auditProgress.processed}/${auditProgress.total}` : `批量审核 (${auditStore.selectedIds.length})` }}
            </span>
          </button>
        </template>
      </div>
    </header>

    <StatsCards v-if="connStore.connected" :stats="auditStore.stats" />

    <div v-if="connStore.connected" class="filter-bar glass-card">
      <div class="filter-item">
        <label class="filter-label">单据状态</label>
        <el-select v-model="statusFilter" placeholder="全部" style="width: 140px">
          <el-option label="全部" value="ALL" />
          <el-option label="待审核" value="PENDING" />
          <el-option label="已通过" value="APPROVE" />
          <el-option label="已驳回" value="REJECT" />
          <el-option label="已存疑" value="FLAG" />
        </el-select>
      </div>
      <div class="filter-item">
        <label class="filter-label">关键字</label>
        <el-input
          v-model="keyword"
          placeholder="单号 / 事由 / 报销人"
          clearable
          style="width: 260px"
          @keyup.enter="handleQuery"
        />
      </div>
      <el-button type="primary" @click="handleQuery">查询</el-button>
      <a class="reset-link" @click="handleReset">重置</a>
    </div>

    <ClaimTable
      v-if="connStore.connected"
      :claims="displayClaims"
      :loading="auditStore.loading"
      :total="auditStore.totalCount"
      :current-page="auditStore.currentPage"
      :page-size="30"
      :audit-status="auditStore.auditStatusMap"
      @view-detail="viewDetail"
      @selection-change="handleSelectionChange"
      @page-change="handlePageChange"
    />

    <el-dialog v-model="showConnectDialog" title="连接 ERP 系统" width="480px" :close-on-click-modal="false">
      <div class="connect-form">
        <div class="form-item">
          <label>ERP API 地址</label>
<el-input v-model="connStore.apiUrl" placeholder="http://host.docker.internal:8081" />
        </div>
        <div class="form-item">
          <label>API Key</label>
          <el-input v-model="connStore.apiKey" type="password" show-password placeholder="输入您的 API Key" />
        </div>
        <div v-if="connStore.error" class="error-msg">
          <el-icon><WarningFilled /></el-icon>
          {{ connStore.error }}
        </div>
      </div>
      <template #footer>
        <button class="btn-primary" :disabled="connStore.connecting" @click="handleConnect">
          {{ connStore.connecting ? '连接中...' : '验证并连接' }}
        </button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.m2-audit-page {
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.writeback-toggle {
  white-space: nowrap;
  margin-right: 2px;
}

.page-title {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.page-subtitle {
  font-size: 14px;
  color: var(--text-muted);
  margin-top: 4px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 20px;
  margin-bottom: 16px;
}

.filter-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
  white-space: nowrap;
}

.reset-link {
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  text-decoration: none;
  user-select: none;
}

.reset-link:hover {
  color: var(--brand);
}

.connect-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-item label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
}

.error-msg {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--danger);
  font-size: 13px;
  padding: 8px 12px;
  background: rgba(229, 72, 77, 0.08);
  border-radius: var(--border-radius-sm);
}
</style>
