<script setup>
import { computed } from 'vue'

const props = defineProps({
  advice: {
    type: Object,
    default: () => null,
  },
})

const emit = defineEmits(['select-suggestion'])

function getTypeColor(type) {
  const map = {
    approve: 'var(--success)',
    reject: 'var(--danger)',
    flag: 'var(--warning)',
  }
  return map[type] || 'var(--brand)'
}

function getTypeIcon(type) {
  const map = {
    approve: 'CircleCheck',
    reject: 'CircleClose',
    flag: 'Warning',
  }
  return map[type] || 'InfoFilled'
}

const verdictMeta = computed(() => {
  if (!props.advice?.result) return null
  const map = {
    APPROVE: { label: 'AI 建议通过', color: 'var(--success)' },
    REJECT: { label: 'AI 建议驳回', color: 'var(--danger)' },
    FLAG: { label: 'AI 建议存疑', color: 'var(--warning)' },
  }
  return map[props.advice.result] || null
})
</script>

<template>
  <div class="ai-advice glass-card">
    <div class="advice-header">
      <div class="title-row">
        <div class="ai-icon">
          <el-icon><MagicStick /></el-icon>
        </div>
        <div>
          <h3 class="title">AI 智能分析</h3>
          <p class="subtitle">基于 10 条审核规则综合评估</p>
        </div>
      </div>
      <div v-if="advice" class="confidence-block">
        <span
          v-if="verdictMeta"
          class="verdict-tag"
          :style="{ '--verdict-color': verdictMeta.color }"
        >
          {{ verdictMeta.label }}
        </span>
        <span class="confidence-label">置信度</span>
        <div class="confidence-bar">
          <div
            class="confidence-fill"
            :style="{ width: (advice.confidence * 100) + '%' }"
          ></div>
        </div>
        <span class="confidence-value">{{ Math.round((advice.confidence || 0) * 100) }}%</span>
      </div>
    </div>

    <div v-if="advice" class="advice-content">
      <div class="summary-block">
        <div class="summary-label">分析摘要</div>
        <p class="summary-text">{{ advice.summary }}</p>
      </div>

      <div v-if="advice.suggestions?.length" class="suggestions">
        <div class="suggestions-label">建议操作</div>
        <div class="suggestion-list">
          <button
            v-for="(s, idx) in advice.suggestions"
            :key="idx"
            class="suggestion-item"
            :style="{ '--accent': getTypeColor(s.type) }"
            @click="emit('select-suggestion', s)"
          >
            <el-icon class="suggestion-icon" :size="16">
              <component :is="getTypeIcon(s.type)" />
            </el-icon>
            <span class="suggestion-text">{{ s.text }}</span>
            <el-icon class="suggestion-arrow"><ArrowRight /></el-icon>
          </button>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">
      <el-icon :size="48"><MagicStick /></el-icon>
      <p>暂无 AI 分析结果</p>
      <span>请先运行批量审核以获取建议</span>
    </div>
  </div>
</template>

<style scoped>
.ai-advice {
  padding: 24px;
  position: relative;
  overflow: hidden;
}

.ai-advice::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--brand), var(--brand-dark), var(--brand));
  background-size: 200% 100%;
  animation: shimmer 3s linear infinite;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.advice-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  flex-wrap: wrap;
  gap: 16px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.ai-icon {
  width: 44px;
  height: 44px;
  background: linear-gradient(135deg, var(--brand), var(--brand-dark));
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #FFFFFF;
  font-size: 22px;
}

.title {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 600;
  margin: 0;
}

.subtitle {
  font-size: 13px;
  color: var(--text-muted);
  margin: 4px 0 0;
}

.confidence-block {
  display: flex;
  align-items: center;
  gap: 10px;
}

.verdict-tag {
  padding: 4px 10px;
  border-radius: 6px;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
  color: var(--verdict-color);
  background: color-mix(in srgb, var(--verdict-color) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--verdict-color) 25%, transparent);
}

.confidence-label {
  font-size: 12px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.confidence-bar {
  width: 120px;
  height: 6px;
  background: var(--bg-tertiary);
  border-radius: 3px;
  overflow: hidden;
}

.confidence-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--brand-dark), var(--brand));
  border-radius: 3px;
  transition: width 0.6s ease;
}

.confidence-value {
  font-family: var(--font-display);
  font-weight: 600;
  color: var(--brand);
  font-size: 13px;
}

.advice-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.summary-block {
  padding: 16px 20px;
  background: rgba(10, 143, 117, 0.05);
  border-left: 3px solid var(--brand);
  border-radius: 0 8px 8px 0;
}

.summary-label {
  font-size: 12px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.summary-text {
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
  margin: 0;
}

.suggestions-label {
  font-size: 12px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}

.suggestion-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.suggestion-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 14px 16px;
  background: var(--bg-tertiary);
  border: 1px solid var(--glass-border);
  border-radius: var(--border-radius-sm);
  color: var(--text-primary);
  font-family: var(--font-body);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: left;
  border-left: 3px solid var(--accent);
}

.suggestion-item:hover {
  background: rgba(10, 143, 117, 0.05);
  border-color: var(--accent);
  transform: translateX(4px);
}

.suggestion-icon {
  color: var(--accent);
  flex-shrink: 0;
}

.suggestion-text {
  flex: 1;
}

.suggestion-arrow {
  color: var(--text-muted);
  transition: transform 0.2s ease;
}

.suggestion-item:hover .suggestion-arrow {
  color: var(--accent);
  transform: translateX(4px);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 0;
  gap: 12px;
  color: var(--text-muted);
}

.empty-state .el-icon {
  color: var(--brand);
  opacity: 0.4;
}

.empty-state p {
  margin: 0;
  font-size: 14px;
  color: var(--text-secondary);
}

.empty-state span {
  font-size: 12px;
}
</style>
