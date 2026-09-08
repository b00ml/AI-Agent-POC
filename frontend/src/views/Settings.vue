<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useConnectionStore } from '../stores/connection'
import api from '../api'

const connStore = useConnectionStore()
const saving = ref(false)
const saved = ref(false)

const ocrEngine = ref('paddle')
const dashscopeKey = ref('')
const qihengKey = ref(connStore.apiKey)
const llmReviewEnabled = ref(false)
const llmReviewModel = ref('')
const llmReviewKeyConfigured = ref(false)
const savingReview = ref(false)

async function save() {
  saving.value = true
  await new Promise(r => setTimeout(r, 800))
  localStorage.setItem('qiheng_api_key', qihengKey.value)
  localStorage.setItem('dashscope_api_key', dashscopeKey.value)
  localStorage.setItem('ocr_engine', ocrEngine.value)
  saved.value = true
  setTimeout(() => { saved.value = false }, 2000)
  saving.value = false
}

onMounted(() => {
  dashscopeKey.value = localStorage.getItem('dashscope_api_key') || ''
  ocrEngine.value = localStorage.getItem('ocr_engine') || 'paddle'
  loadLlmReview()
})

async function loadLlmReview() {
  try {
    const data = await api.get('/settings/llm-review')
    llmReviewEnabled.value = !!data.enabled
    llmReviewModel.value = data.model || ''
    llmReviewKeyConfigured.value = !!data.keyConfigured
  } catch (e) {
    console.warn('加载 AI 复核设置失败', e)
  }
}

async function toggleLlmReview(val) {
  savingReview.value = true
  try {
    const data = await api.put('/settings/llm-review', { enabled: val })
    llmReviewEnabled.value = !!data.enabled
    llmReviewModel.value = data.model || ''
    llmReviewKeyConfigured.value = !!data.keyConfigured
    ElMessage.success(val ? 'AI 复核助手已开启：审核时大模型独立复核，分歧自动转 FLAG' : 'AI 复核助手已关闭')
  } catch (e) {
    llmReviewEnabled.value = !val
    ElMessage.error('切换失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    savingReview.value = false
  }
}
</script>

<template>
  <div class="settings-page">
    <header class="page-header">
      <h1 class="page-title">系统设置</h1>
      <p class="page-subtitle">API 配置、OCR 引擎、审核选项</p>
    </header>

    <div class="settings-sections">
      <div class="section glass-card">
        <div class="section-header">
          <el-icon class="section-icon"><MagicStick /></el-icon>
          <div>
            <h3>AI 复核助手</h3>
            <p>大模型结合 OCR 结果与制度知识库独立复核，与规则引擎交叉验证</p>
          </div>
        </div>
        <div class="section-body">
          <div class="form-item">
            <div class="switch-row">
              <div class="switch-text">
                <span class="switch-title">启用 AI 复核</span>
                <span class="switch-desc">
                  开启后：每单由大模型独立复核（只看 OCR 提取结果 + 制度条款，不读票据图片），
                  与规则引擎意见不一致时自动转 FLAG 提请人工复核。
                  单据字段（不含图片）将发送至 {{ llmReviewModel || 'DeepSeek' }}。
                </span>
                <span v-if="!llmReviewKeyConfigured" class="switch-warn">
                  未配置模型 API Key，无法启用
                </span>
              </div>
              <el-switch
                v-model="llmReviewEnabled"
                :disabled="!llmReviewKeyConfigured || savingReview"
                @change="toggleLlmReview"
              />
            </div>
          </div>
        </div>
      </div>

      <div class="section glass-card">
        <div class="section-header">
          <el-icon class="section-icon"><Key /></el-icon>
          <div>
            <h3>API 配置</h3>
            <p>配置 ERP 和第三方服务的访问密钥</p>
          </div>
        </div>
        <div class="section-body">
          <div class="form-item">
            <label>启衡 ERP API Key</label>
            <el-input v-model="qihengKey" type="password" show-password placeholder="输入 API Key" />
          </div>
          <div class="form-item">
            <label>阿里云百炼 DashScope API Key（可选）</label>
            <el-input v-model="dashscopeKey" type="password" show-password placeholder="用于云端 OCR 备用" />
          </div>
        </div>
      </div>

      <div class="section glass-card">
        <div class="section-header">
          <el-icon class="section-icon"><Cpu /></el-icon>
          <div>
            <h3>OCR 引擎</h3>
            <p>选择发票识别引擎（修改后需重启服务）</p>
          </div>
        </div>
        <div class="section-body">
          <div class="radio-group">
            <label class="radio-item" :class="{ active: ocrEngine === 'paddle' }">
              <input type="radio" v-model="ocrEngine" value="paddle" />
              <div class="radio-content">
                <span class="radio-title">PaddleOCR（本地）</span>
                <span class="radio-desc">数据不出域，推荐用于敏感数据场景</span>
              </div>
            </label>
            <label class="radio-item" :class="{ active: ocrEngine === 'qwen' }">
              <input type="radio" v-model="ocrEngine" value="qwen" />
              <div class="radio-content">
                <span class="radio-title">千问 VL（云端）</span>
                <span class="radio-desc">阿里云 DashScope，识别精度高但数据上云</span>
              </div>
            </label>
          </div>
        </div>
      </div>

      <div class="section glass-card">
        <div class="section-header">
          <el-icon class="section-icon"><InfoFilled /></el-icon>
          <div>
            <h3>系统信息</h3>
            <p>当前运行环境和版本信息</p>
          </div>
        </div>
        <div class="section-body">
          <div class="info-grid">
            <div class="info-row">
              <span class="info-label">系统版本</span>
              <span class="info-value mono">v2.0.0</span>
            </div>
            <div class="info-row">
              <span class="info-label">前端框架</span>
              <span class="info-value">Vue 3.4 + Vite 5</span>
            </div>
            <div class="info-row">
              <span class="info-label">后端框架</span>
              <span class="info-value">FastAPI 0.110</span>
            </div>
            <div class="info-row">
              <span class="info-label">部署模式</span>
              <span class="info-value">Docker Compose</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="actions-bar">
      <div v-if="saved" class="save-msg">
        <el-icon><CircleCheck /></el-icon>
        <span>设置已保存</span>
      </div>
      <button class="btn-primary" :disabled="saving" @click="save">
        <el-icon v-if="!saving"><Check /></el-icon>
        <span style="margin-left: 6px">{{ saving ? '保存中...' : '保存设置' }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.settings-page { max-width: 900px; margin: 0 auto; }

.page-header { margin-bottom: 24px; }
.page-title {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}
.page-subtitle { font-size: 14px; color: var(--text-muted); margin-top: 4px; }

.settings-sections {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-bottom: 80px;
}

.section { padding: 0; overflow: hidden; }

.section-header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 20px 24px;
  border-bottom: 1px solid var(--glass-border);
}

.section-icon {
  width: 40px;
  height: 40px;
  background: rgba(10, 143, 117, 0.1);
  color: var(--brand);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.section-header h3 {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 600;
  margin: 0;
}

.section-header p {
  font-size: 13px;
  color: var(--text-muted);
  margin: 4px 0 0;
}

.section-body { padding: 24px; }

.form-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 20px;
}

.form-item:last-child { margin-bottom: 0; }

.form-item label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
}

.radio-group {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.radio-item {
  display: flex;
  cursor: pointer;
  padding: 16px 20px;
  background: var(--bg-tertiary);
  border: 2px solid var(--glass-border);
  border-radius: var(--border-radius);
  transition: all 0.2s;
}

.radio-item.active {
  border-color: var(--brand);
  background: rgba(10, 143, 117, 0.05);
}

.radio-item input { display: none; }

.radio-content { display: flex; flex-direction: column; gap: 4px; }
.radio-title { font-weight: 600; font-size: 14px; }
.radio-desc { font-size: 12px; color: var(--text-muted); }

.switch-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
}

.switch-text {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.switch-title { font-weight: 600; font-size: 14px; }
.switch-desc { font-size: 12px; color: var(--text-muted); line-height: 1.6; }
.switch-warn { font-size: 12px; color: var(--danger); }

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px 32px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid var(--glass-border);
}

.info-label { font-size: 13px; color: var(--text-muted); }
.info-value { font-size: 13px; color: var(--text-primary); }

.actions-bar {
  position: fixed;
  bottom: 0;
  left: var(--sidebar-width);
  right: 0;
  padding: 16px 32px;
  background: linear-gradient(180deg, transparent, var(--bg-primary) 20%);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.save-msg {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--success);
  font-size: 14px;
}
</style>
