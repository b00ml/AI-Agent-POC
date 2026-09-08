<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  invoices: {
    type: Array,
    default: () => [],
  },
})

const expandedId = ref(null)

const totalAmount = computed(() =>
  props.invoices.reduce((sum, i) => sum + i.amount, 0)
)

function toggleExpand(id) {
  expandedId.value = expandedId.value === id ? null : id
}
</script>

<template>
  <div class="invoice-compare glass-card">
    <div class="panel-header">
      <div class="panel-title">
        <el-icon><Files /></el-icon>
        <span>发票明细</span>
      </div>
      <div class="panel-summary">
        <span>共 {{ invoices.length }} 张发票</span>
        <span class="total">合计 ¥{{ totalAmount.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</span>
      </div>
    </div>

    <div class="invoice-list">
      <div
        v-for="inv in invoices"
        :key="inv.id"
        class="invoice-item"
        :class="{ expanded: expandedId === inv.id }"
        @click="toggleExpand(inv.id)"
      >
        <div class="invoice-main">
          <div class="invoice-type" :class="inv.category">
            {{ inv.category }}
          </div>
          <div class="invoice-info">
            <div class="invoice-vendor">{{ inv.vendor }}</div>
            <div class="invoice-meta">
              <span class="mono">{{ inv.id }}</span>
              <span class="dot">·</span>
              <span>{{ inv.date }}</span>
            </div>
          </div>
          <div class="invoice-amount">
            ¥{{ inv.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}
          </div>
          <el-icon class="chevron" :class="{ rotated: expandedId === inv.id }">
            <ArrowRight />
          </el-icon>
        </div>

        <div v-if="expandedId === inv.id" class="invoice-detail">
          <div class="detail-grid">
            <div class="detail-row">
              <span class="detail-label">发票代码</span>
              <span class="detail-value mono">{{ inv.code }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">金额</span>
              <span class="detail-value">¥{{ inv.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">类型</span>
              <span class="detail-value">{{ inv.category }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.invoice-compare {
  padding: 0;
  overflow: hidden;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid var(--glass-border);
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 15px;
}

.panel-title .el-icon {
  color: var(--brand);
}

.panel-summary {
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 13px;
  color: var(--text-muted);
}

.panel-summary .total {
  font-family: var(--font-display);
  font-weight: 600;
  color: var(--brand);
}

.invoice-list {
  display: flex;
  flex-direction: column;
}

.invoice-item {
  cursor: pointer;
  transition: background 0.2s ease;
  border-bottom: 1px solid var(--glass-border);
}

.invoice-item:last-child {
  border-bottom: none;
}

.invoice-item:hover {
  background: rgba(10, 143, 117, 0.03);
}

.invoice-main {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 24px;
}

.invoice-type {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 12px;
  background: var(--bg-tertiary);
  color: var(--brand);
  border-radius: 6px;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
  min-width: 52px;
}

.invoice-type.机票,
.invoice-type.住宿,
.invoice-type.餐饮,
.invoice-type.交通 { color: var(--brand); }

.invoice-info {
  flex: 1;
}

.invoice-vendor {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.invoice-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-muted);
}

.invoice-meta .dot {
  opacity: 0.5;
}

.invoice-amount {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
  text-align: right;
  min-width: 120px;
}

.chevron {
  color: var(--text-muted);
  transition: transform 0.2s ease;
}

.chevron.rotated {
  transform: rotate(90deg);
}

.invoice-detail {
  padding: 0 24px 20px;
  animation: fadeIn 0.2s ease;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  padding-top: 16px;
  border-top: 1px dashed var(--glass-border);
}

.detail-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.detail-label {
  font-size: 12px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.detail-value {
  font-family: var(--font-display);
  font-size: 13px;
  color: var(--text-primary);
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
