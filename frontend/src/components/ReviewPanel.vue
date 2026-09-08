<script setup>
import { ref } from 'vue'

const props = defineProps({
  claim: {
    type: Object,
    default: () => null,
  },
})

const emit = defineEmits(['submit'])

const decision = ref('')
const comment = ref('')
const submitting = ref(false)

const decisions = [
  { value: 'APPROVE', label: '通过', icon: 'CircleCheck' },
  { value: 'FLAG', label: '存疑', icon: 'Warning' },
  { value: 'REJECT', label: '驳回', icon: 'CircleClose' },
]

const decisionColors = {
  APPROVE: 'var(--success)',
  REJECT: 'var(--danger)',
  FLAG: 'var(--warning)',
}

async function submit() {
  if (!decision.value) return
  submitting.value = true
  try {
    emit('submit', {
      claimId: props.claim?.id,
      decision: decision.value,
      comment: comment.value,
    })
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="review-panel glass-card">
    <div class="panel-header">
      <div class="header-left">
        <el-icon class="header-icon"><EditPen /></el-icon>
        <h3 class="panel-title">人工复核</h3>
      </div>
      <span class="panel-desc">请选择最终审核结论并提交</span>
    </div>

    <div class="panel-body">
      <div class="decision-group">
        <div class="group-label">审核决定</div>
        <div class="decision-buttons">
          <button
            v-for="d in decisions"
            :key="d.value"
            :class="['decision-btn', { active: decision === d.value }]"
            :style="{ '--decision-color': decisionColors[d.value] }"
            @click="decision = d.value"
          >
            <el-icon :size="20">
              <component :is="d.icon" />
            </el-icon>
            <span>{{ d.label }}</span>
          </button>
        </div>
      </div>

      <div class="comment-group">
        <div class="group-label">复核备注 <span class="optional">(可选)</span></div>
        <el-input
          v-model="comment"
          type="textarea"
          :rows="4"
          placeholder="请输入审核意见或补充说明..."
          resize="none"
        />
      </div>
    </div>

    <div class="panel-footer">
      <div class="footer-info">
        <el-icon><InfoFilled /></el-icon>
        <span>操作将记录至审计日志，不可撤销</span>
      </div>
      <div class="footer-actions">
        <button
          class="btn-primary submit-btn"
          :disabled="!decision || submitting"
          @click="submit"
        >
          <el-icon v-if="!submitting"><Promotion /></el-icon>
          <span>{{ submitting ? '提交中...' : '提交审核决定' }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.review-panel {
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

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-icon {
  color: var(--brand);
  font-size: 20px;
}

.panel-title {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 600;
  margin: 0;
}

.panel-desc {
  font-size: 13px;
  color: var(--text-muted);
}

.panel-body {
  padding: 28px 24px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.group-label {
  font-size: 12px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}

.group-label .optional {
  text-transform: none;
  font-size: 12px;
  color: var(--text-muted);
}

.decision-buttons {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.decision-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px 16px;
  background: var(--bg-tertiary);
  border: 2px solid var(--glass-border);
  border-radius: var(--border-radius);
  color: var(--text-secondary);
  font-family: var(--font-body);
  font-weight: 500;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.decision-btn:hover {
  border-color: var(--decision-color);
  color: var(--decision-color);
  transform: translateY(-2px);
}

.decision-btn.active {
  background: color-mix(in srgb, var(--decision-color) 10%, transparent);
  border-color: var(--decision-color);
  color: var(--decision-color);
  box-shadow: 0 4px 20px color-mix(in srgb, var(--decision-color) 22%, transparent);
}

.comment-group :deep(.el-textarea__inner) {
  background: var(--bg-tertiary) !important;
  border: 1px solid var(--glass-border) !important;
  border-radius: var(--border-radius-sm) !important;
  color: var(--text-primary) !important;
  padding: 14px 16px !important;
  font-family: var(--font-body) !important;
  line-height: 1.6 !important;
}

.comment-group :deep(.el-textarea__inner:focus) {
  border-color: var(--brand) !important;
}

.panel-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-top: 1px solid var(--glass-border);
  background: #FAFBFC;
}

.footer-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-muted);
}

.footer-info .el-icon {
  color: var(--brand);
  opacity: 0.6;
}

.submit-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
</style>
