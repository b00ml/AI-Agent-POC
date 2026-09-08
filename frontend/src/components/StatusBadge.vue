<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['click'])

const statusMap = {
  PENDING: { label: '待审核', icon: 'Clock' },
  APPROVE: { label: '已通过', icon: 'CircleCheck' },
  REJECT: { label: '已驳回', icon: 'CircleClose' },
  FLAG: { label: '存疑', icon: 'Warning' },
  PROCESSING: { label: '审核中', icon: 'Loading' },
  WAIT_AUDIT: { label: '待审核', icon: 'Clock' },
  AI_REVIEWED: { label: 'AI审核', icon: 'Cpu' },
  WRITTEN_BACK: { label: '已写回', icon: 'Upload' },
}

const info = computed(() => statusMap[props.status] || {
  label: props.status || '未知',
  icon: 'QuestionFilled',
})

const colorMap = {
  APPROVE: 'var(--success)',
  REJECT: 'var(--danger)',
  FLAG: 'var(--warning)',
  PENDING: 'var(--brand)',
  WAIT_AUDIT: '#909399',
  AI_REVIEWED: 'var(--brand)',
  WRITTEN_BACK: '#0e9f8e',
}

const badgeColor = computed(() => colorMap[props.status] || 'var(--brand)')
</script>

<template>
  <span class="status-badge" :style="{ '--badge-color': badgeColor }" @click="$emit('click')">
    <el-icon :size="12" class="badge-icon">
      <component :is="info.icon" />
    </el-icon>
    <span class="badge-label">{{ info.label }}</span>
  </span>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: color-mix(in srgb, var(--badge-color) 8%, transparent);
  color: var(--badge-color);
  border: 1px solid color-mix(in srgb, var(--badge-color) 22%, transparent);
  border-radius: 6px;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 500;
  cursor: inherit;
  transition: all 0.2s ease;
}

.badge-icon {
  flex-shrink: 0;
}
</style>
