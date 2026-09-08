<script setup>
import { computed } from 'vue'

const props = defineProps({
  stats: {
    type: Object,
    required: true,
  },
})

const cards = computed(() => [
  { label: '总单数', value: props.stats.total || 0, icon: 'Tickets', color: 'var(--brand)' },
  { label: '合规通过', value: props.stats.approved || 0, icon: 'CircleCheck', color: 'var(--success)' },
  { label: '驳回', value: props.stats.rejected || 0, icon: 'CircleClose', color: 'var(--danger)' },
  { label: '存疑', value: props.stats.flagged || 0, icon: 'Warning', color: 'var(--warning)' },
])
</script>

<template>
  <div class="stats-cards">
    <div
      v-for="card in cards"
      :key="card.label"
      class="stat-card glass-card"
      :style="{ '--card-color': card.color }"
    >
      <div class="stat-icon">
        <el-icon :size="22">
          <component :is="card.icon" />
        </el-icon>
      </div>
      <div class="stat-content">
        <div class="stat-value">{{ card.value }}</div>
        <div class="stat-label">{{ card.label }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stats-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px 24px;
  min-height: 88px;
  position: relative;
  overflow: hidden;
}

.stat-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--card-color);
  opacity: 0.6;
}

.stat-card::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  width: 80px;
  height: 80px;
  background: radial-gradient(circle, color-mix(in srgb, var(--card-color) 8%, transparent), transparent 70%);
  border-radius: 50%;
  pointer-events: none;
}

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--card-color) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--card-color) 18%, transparent);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--card-color);
}

.stat-content {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--text-primary);
}

.stat-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
</style>
