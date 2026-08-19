<template>
  <div class="page-shell" v-loading="loading">
    <div class="page-heading">
      <h1>模拟打印配置</h1>
      <div class="page-actions">
        <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
        <el-button type="primary" :icon="DocumentChecked" :loading="saving" @click="saveConfig">
          保存并应用
        </el-button>
      </div>
    </div>

    <div class="configuration-summary">
      <div class="summary-item">
        <span>当前状态</span>
        <strong :class="form.active ? 'success-text' : ''">{{ form.active ? "打印模式运行中" : "配置待下次切换生效" }}</strong>
      </div>
      <div class="summary-item">
        <span>驱动类型</span>
        <strong>{{ selectedProfile?.label || "-" }}</strong>
      </div>
      <div class="summary-item wide">
        <span>向主机声明的协议</span>
        <strong>{{ selectedProfile?.commands || "-" }}</strong>
      </div>
      <div class="summary-item">
        <span>任务结束判定</span>
        <strong class="success-text">{{ form.boundary_detection?.enabled ? "智能协议优先" : "仅超时判断" }}</strong>
      </div>
    </div>

    <el-form ref="formRef" :model="form" label-position="top">
      <section class="surface">
        <div class="surface-heading"><h2>USB 打印设备</h2></div>
        <div class="form-grid">
          <el-form-item label="模拟驱动类型" prop="driver_profile">
            <el-select v-model="form.driver_profile">
              <el-option
                v-for="item in form.driver_profiles"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="打印机名称" prop="usb_product" :rules="textRules('请输入打印机名称')">
            <el-input v-model="form.usb_product" maxlength="96" />
          </el-form-item>
          <el-form-item label="设备序列号" prop="usb_serial" :rules="textRules('请输入设备序列号')">
            <el-input v-model="form.usb_serial" maxlength="64" />
          </el-form-item>
          <el-form-item label="未知/异常打印流兜底等待（秒）">
            <el-input-number v-model="form.idle_complete_seconds" :min="0.5" :max="120" :step="0.5" controls-position="right" />
            <div class="field-help">PJL、PCL、PCL XL、PostScript和PDF优先按协议结束，不等待该时间。</div>
          </el-form-item>
          <el-form-item label="最小任务大小（字节）">
            <el-input-number v-model="form.min_job_bytes" :min="1" :max="10485760" controls-position="right" />
          </el-form-item>
        </div>
      </section>
    </el-form>

    <section class="surface reports-table">
      <div class="surface-heading">
        <h2>最近打印流协议分析</h2>
        <el-button :icon="Refresh" :loading="analysisLoading" @click="loadAnalysis">刷新分析</el-button>
      </div>
      <el-table :data="jobs" stripe height="390" class="desktop-only">
        <el-table-column label="接收时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.first_byte_at) !== "-" ? formatDateTime(row.first_byte_at) : formatTime(row.modified_at) }}</template>
        </el-table-column>
        <el-table-column prop="name" label="PRN 文件" min-width="270" show-overflow-tooltip />
        <el-table-column label="大小" width="110">
          <template #default="{ row }">{{ formatBytes(row.size) }}</template>
        </el-table-column>
        <el-table-column prop="protocol_label" label="识别协议" width="145" />
        <el-table-column label="结束依据" width="150">
          <template #default="{ row }">{{ row.completion_reason_label || "-" }}</template>
        </el-table-column>
        <el-table-column label="接收耗时" width="115">
          <template #default="{ row }">{{ formatDuration(row.receive_duration_ms) }}</template>
        </el-table-column>
        <el-table-column label="转换耗时" width="115">
          <template #default="{ row }">{{ formatDuration(row.conversion_duration_ms) }}</template>
        </el-table-column>
        <el-table-column label="转换状态" width="120">
          <template #default="{ row }">
            <el-tag :type="conversionType(row.conversion_status)" effect="light">{{ row.conversion_status_label || "-" }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="PJL 声明" width="130">
          <template #default="{ row }">{{ row.declared_language || "-" }}</template>
        </el-table-column>
        <el-table-column label="可信度" width="100">
          <template #default="{ row }">
            <el-tag :type="confidenceType(row.confidence)" effect="light">{{ confidenceName(row.confidence) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="converter" label="处理方式" width="120" />
        <el-table-column prop="evidence" label="判断依据" min-width="220" show-overflow-tooltip />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="View" @click="showAnalysis(row)">查看分析</el-button>
            <el-button link type="primary" :icon="Download" @click="downloadPrn(row)">下载 PRN</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无打印流" :image-size="80" /></template>
      </el-table>
      <div v-loading="analysisLoading" class="mobile-only mobile-record-list">
        <article v-for="row in jobs" :key="row.name" class="mobile-record">
          <div class="mobile-record-heading">
            <div>
              <strong>{{ row.name }}</strong>
              <span>{{ formatDateTime(row.first_byte_at) !== "-" ? formatDateTime(row.first_byte_at) : formatTime(row.modified_at) }} · {{ formatBytes(row.size) }}</span>
            </div>
            <el-tag :type="confidenceType(row.confidence)" effect="light">
              {{ confidenceName(row.confidence) }}可信度
            </el-tag>
          </div>
          <dl class="mobile-record-meta">
            <dt>识别协议</dt>
            <dd>{{ row.protocol_label }}</dd>
            <dt>结束依据</dt>
            <dd>{{ row.completion_reason_label || "-" }}</dd>
            <dt>接收耗时</dt>
            <dd>{{ formatDuration(row.receive_duration_ms) }}</dd>
            <dt>转换耗时</dt>
            <dd>{{ formatDuration(row.conversion_duration_ms) }}</dd>
            <dt>转换状态</dt>
            <dd>{{ row.conversion_status_label || "-" }}</dd>
            <dt>PJL 声明</dt>
            <dd>{{ row.declared_language || "-" }}</dd>
            <dt>处理方式</dt>
            <dd>{{ row.converter }}</dd>
            <dt>判断依据</dt>
            <dd>{{ row.evidence || "-" }}</dd>
          </dl>
          <div class="mobile-record-actions">
            <el-button type="primary" plain :icon="View" @click="showAnalysis(row)">查看分析</el-button>
            <el-button :icon="Download" @click="downloadPrn(row)">下载 PRN</el-button>
          </div>
        </article>
        <el-empty v-if="!analysisLoading && jobs.length === 0" description="暂无打印流" :image-size="76" />
      </div>
    </section>

    <el-dialog v-model="analysisVisible" class="analysis-dialog" title="打印流详细分析" width="860px">
      <dl v-if="selectedJob" class="detail-list">
        <dt>PRN 文件</dt>
        <dd>{{ selectedJob.name }}</dd>
        <dt>文件大小</dt>
        <dd>{{ formatBytes(selectedJob.size) }}</dd>
        <dt>识别协议</dt>
        <dd>{{ selectedJob.protocol_label }}（{{ confidenceName(selectedJob.confidence) }}置信度）</dd>
        <dt>结束判定</dt>
        <dd>{{ selectedJob.completion_reason_label || "旧任务无采集元数据" }}</dd>
        <dt>首字节时间</dt>
        <dd>{{ formatDateTime(selectedJob.first_byte_at) }}</dd>
        <dt>末字节时间</dt>
        <dd>{{ formatDateTime(selectedJob.last_byte_at) }}</dd>
        <dt>边界确认时间</dt>
        <dd>{{ formatDateTime(selectedJob.boundary_detected_at) }}</dd>
        <dt>打印流接收耗时</dt>
        <dd>{{ formatDuration(selectedJob.receive_duration_ms) }}</dd>
        <dt>任务完成耗时</dt>
        <dd>{{ formatDuration(selectedJob.completion_duration_ms) }}</dd>
        <dt>PDF转换</dt>
        <dd>{{ selectedJob.conversion_status_label || "-" }}，耗时 {{ formatDuration(selectedJob.conversion_duration_ms) }}</dd>
        <dt>PDF就绪时间</dt>
        <dd>{{ formatDateTime(selectedJob.pdf_ready_at) }}</dd>
        <dt v-if="selectedJob.conversion_error">转换错误</dt>
        <dd v-if="selectedJob.conversion_error" class="detail-block">{{ selectedJob.conversion_error }}</dd>
        <dt v-if="selectedJob.conversion_skip_reason">忽略原因</dt>
        <dd v-if="selectedJob.conversion_skip_reason" class="detail-block">{{ selectedJob.conversion_skip_reason }}</dd>
        <dt>PJL 声明语言</dt>
        <dd>{{ selectedJob.declared_language || "未声明" }}</dd>
        <dt>处理方式</dt>
        <dd>{{ selectedJob.converter }}：{{ selectedJob.conversion_detail }}</dd>
        <dt>判断依据</dt>
        <dd>{{ selectedJob.evidence }}</dd>
        <dt>SHA-256</dt>
        <dd class="detail-block monospace">{{ selectedJob.sha256 || "-" }}</dd>
        <dt>分析采样</dt>
        <dd>文件前 {{ formatBytes(selectedJob.sampled_bytes) }}（哈希覆盖完整文件）</dd>
        <dt>文件头 HEX</dt>
        <dd class="detail-block monospace">{{ selectedJob.header_hex || "-" }}</dd>
        <dt>文件头 ASCII</dt>
        <dd class="detail-block monospace">{{ selectedJob.header_ascii || "-" }}</dd>
        <dt>PJL 命令</dt>
        <dd class="detail-block monospace">{{ selectedJob.pjl_commands?.join("\n") || "未检测到 PJL 命令" }}</dd>
      </dl>
      <template #footer>
        <el-button :icon="Download" @click="downloadPrn(selectedJob)">下载原始 PRN</el-button>
        <el-button type="primary" @click="analysisVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { DocumentChecked, Download, Refresh, View } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, errorMessage } from "@/api/client";
import { formatBytes, formatDateTime, formatTime } from "@/utils/format";

const formRef = ref();
const loading = ref(false);
const saving = ref(false);
const analysisLoading = ref(false);
const jobs = ref([]);
const analysisVisible = ref(false);
const selectedJob = ref(null);
const ANALYSIS_REFRESH_MS = 5000;
let analysisRefreshTimer = null;
let analysisRequestPending = false;
const form = reactive({
  driver_profile: "universal",
  driver_profiles: [],
  usb_product: "K2B USB Printer",
  usb_serial: "K2B-H618-PRINTER-001",
  idle_complete_seconds: 20,
  min_job_bytes: 128,
  boundary_detection: {
    enabled: true,
    mode: "protocol_first",
    supported_protocols: [],
    ambiguous_marker_grace_ms: 200
  },
  active: false
});
const selectedProfile = computed(() => form.driver_profiles.find((item) => item.value === form.driver_profile));
const textRules = (message) => [{ required: true, message, trigger: "blur" }];

async function loadConfig() {
  const { data } = await api.get("/api/printer/config");
  Object.assign(form, data);
}

async function loadAnalysis(options = {}) {
  const silent = options?.silent === true;
  if (analysisRequestPending) return;
  analysisRequestPending = true;
  if (!silent) analysisLoading.value = true;
  try {
    const { data } = await api.get("/api/printer/analysis", { params: { limit: 30 } });
    jobs.value = data.jobs || [];
  } catch (error) {
    if (!silent) ElMessage.error(errorMessage(error, "加载打印流分析失败"));
  } finally {
    analysisRequestPending = false;
    if (!silent) analysisLoading.value = false;
  }
}

async function loadAll() {
  loading.value = true;
  try {
    await Promise.all([loadConfig(), loadAnalysis()]);
  } catch (error) {
    ElMessage.error(errorMessage(error, "加载模拟打印配置失败"));
  } finally {
    loading.value = false;
  }
}

async function saveConfig() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid || saving.value) return;
  if (form.active) {
    try {
      await ElMessageBox.confirm("保存后 Windows 会短暂断开并重新识别 USB 打印机。", "应用打印配置", {
        type: "warning",
        confirmButtonText: "保存并重建",
        cancelButtonText: "取消"
      });
    } catch {
      return;
    }
  }
  saving.value = true;
  try {
    const { data } = await api.put("/api/printer/config", {
      driver_profile: form.driver_profile,
      usb_product: form.usb_product,
      usb_serial: form.usb_serial,
      idle_complete_seconds: form.idle_complete_seconds,
      min_job_bytes: form.min_job_bytes
    });
    ElMessage.success(data.applied ? "打印配置已保存并应用" : "打印配置已保存");
    await loadAll();
  } catch (error) {
    ElMessage.error(errorMessage(error, "保存模拟打印配置失败"));
  } finally {
    saving.value = false;
  }
}

function showAnalysis(row) {
  selectedJob.value = row;
  analysisVisible.value = true;
}

function downloadPrn(row) {
  if (!row?.name) return;
  const link = document.createElement("a");
  link.href = `/api/printer/files/${encodeURIComponent(row.name)}/download`;
  link.download = row.name;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function confidenceType(value) {
  return value === "high" ? "success" : value === "medium" ? "warning" : "info";
}

function confidenceName(value) {
  return value === "high" ? "高" : value === "medium" ? "中" : "低";
}

function conversionType(value) {
  return value === "completed" ? "success" : value === "failed" ? "danger" : value === "running" ? "warning" : "info";
}

function formatDuration(value) {
  if (value === null || value === undefined || value === "") return "-";
  const milliseconds = Number(value);
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return "-";
  if (milliseconds < 1000) return `${milliseconds.toFixed(milliseconds < 10 ? 1 : 0)} ms`;
  return `${(milliseconds / 1000).toFixed(3)} s`;
}

function refreshVisibleAnalysis() {
  if (!document.hidden && !analysisVisible.value) {
    void loadAnalysis({ silent: true });
  }
}

onMounted(async () => {
  await loadAll();
  analysisRefreshTimer = window.setInterval(refreshVisibleAnalysis, ANALYSIS_REFRESH_MS);
  document.addEventListener("visibilitychange", refreshVisibleAnalysis);
});

onBeforeUnmount(() => {
  if (analysisRefreshTimer !== null) window.clearInterval(analysisRefreshTimer);
  document.removeEventListener("visibilitychange", refreshVisibleAnalysis);
});
</script>
