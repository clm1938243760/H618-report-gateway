<template>
  <div class="page-shell physical-printer-page" v-loading="loading">
    <div class="page-heading">
      <div>
        <h1>实体打印机配置</h1>
        <p>配置报告 PDF 的实体打印队列；模拟打印采集与实体打印输出相互独立。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="scanning" @click="scanDevices">扫描打印机</el-button>
        <el-button type="primary" :icon="DocumentChecked" :loading="saving" @click="saveConfig">
          保存并应用
        </el-button>
      </div>
    </div>

    <div class="configuration-summary physical-summary">
      <div class="summary-item">
        <span>CUPS 服务</span>
        <strong :class="cups.running ? 'success-text' : 'warning-text'">
          {{ cups.running ? "运行中" : cups.available ? "未运行" : "未安装" }}
        </strong>
      </div>
      <div class="summary-item">
        <span>检测到的设备</span>
        <strong>{{ cups.devices.length }} 台</strong>
      </div>
      <div class="summary-item">
        <span>当前队列</span>
        <strong>{{ configuredQueue?.name || "未创建" }}</strong>
      </div>
      <div class="summary-item">
        <span>自动打印</span>
        <strong :class="form.auto_print ? 'success-text' : ''">{{ form.auto_print ? "已启用" : "未启用" }}</strong>
      </div>
    </div>

    <el-alert
      v-if="cups.error"
      :title="cups.error"
      type="warning"
      :closable="false"
      show-icon
      class="page-alert"
    />

    <section class="surface">
      <div class="surface-heading">
        <div>
          <h2>打印机发现</h2>
          <p class="section-note physical-heading-note">USB 打印机需连接板子的 USB Host 口；网络打印机也可手工填写 URI。</p>
        </div>
        <el-tag v-if="cups.devices.length" type="success" effect="light">已发现 {{ cups.devices.length }} 台</el-tag>
      </div>
      <el-table :data="cups.devices" stripe max-height="260" class="desktop-only">
        <el-table-column prop="label" label="设备" min-width="250" show-overflow-tooltip />
        <el-table-column prop="connection" label="连接方式" width="110" />
        <el-table-column prop="uri" label="设备 URI" min-width="390" show-overflow-tooltip />
        <el-table-column label="推荐驱动" width="220">
          <template #default="{ row }">{{ profileLabel(row.recommended_profile) || "请按设备型号选择" }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="selectDevice(row)">选择</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="未发现实体打印机，可扫描或手工填写设备 URI" :image-size="72" />
        </template>
      </el-table>
      <div class="mobile-only mobile-record-list compact-record-list">
        <article v-for="row in cups.devices" :key="row.uri" class="mobile-record">
          <div class="mobile-record-heading">
            <div>
              <strong>{{ row.label }}</strong>
              <span>{{ row.connection }}</span>
            </div>
          </div>
          <dl class="mobile-record-meta">
            <dt>设备 URI</dt>
            <dd>{{ row.uri }}</dd>
            <dt>推荐驱动</dt>
            <dd>{{ profileLabel(row.recommended_profile) || "请按设备型号选择" }}</dd>
          </dl>
          <div class="mobile-record-actions">
            <el-button type="primary" @click="selectDevice(row)">选择此打印机</el-button>
          </div>
        </article>
        <el-empty v-if="cups.devices.length === 0" description="未发现实体打印机" :image-size="70" />
      </div>
    </section>

    <el-form ref="formRef" :model="form" label-position="top">
      <section class="surface">
        <div class="surface-heading"><h2>队列与驱动</h2></div>
        <div class="form-grid physical-printer-form">
          <el-form-item label="启用实体打印" prop="enabled">
            <el-switch v-model="form.enabled" inline-prompt active-text="开" inactive-text="关" @change="onEnabledChange" />
          </el-form-item>
          <el-form-item label="PDF 生成后自动打印">
            <el-switch
              v-model="form.auto_print"
              :disabled="!form.enabled"
              inline-prompt
              active-text="开"
              inactive-text="关"
            />
          </el-form-item>
          <el-form-item label="设为系统默认队列">
            <el-switch v-model="form.set_default" inline-prompt active-text="是" inactive-text="否" />
          </el-form-item>
          <el-form-item label="队列名称" prop="queue_name" :rules="queueRules">
            <el-input v-model.trim="form.queue_name" maxlength="64" placeholder="Physical_Printer" />
          </el-form-item>
          <el-form-item class="physical-uri-field" label="设备 URI" prop="device_uri">
            <el-input
              v-model.trim="form.device_uri"
              :disabled="!form.enabled"
              placeholder="usb://... 或 ipp://、ipps://、socket://、lpd://"
            />
          </el-form-item>
          <el-form-item label="打印机驱动" prop="driver_profile">
            <el-select v-model="form.driver_profile" :disabled="!form.enabled" style="width: 100%">
              <el-option
                v-for="profile in cups.profiles"
                :key="profile.value"
                :label="profile.label"
                :value="profile.value"
                :disabled="!profile.available"
              >
                <span>{{ profile.label }}</span>
                <span class="profile-availability">{{ profile.available ? "已安装" : "未安装" }}</span>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="纸张">
            <el-select v-model="form.page_size" style="width: 100%">
              <el-option label="A4" value="A4" />
              <el-option label="A5" value="A5" />
              <el-option label="Letter" value="Letter" />
            </el-select>
          </el-form-item>
          <el-form-item label="分辨率">
            <el-select v-model="form.resolution" style="width: 100%">
              <el-option label="300 dpi" value="300dpi" />
              <el-option label="600 dpi" value="600dpi" />
              <el-option label="1200 dpi" value="1200dpi" />
            </el-select>
          </el-form-item>
          <el-form-item label="份数">
            <el-input-number v-model="form.copies" :min="1" :max="99" controls-position="right" />
          </el-form-item>
        </div>
        <p class="section-note">
          HP LaserJet Pro 400 M401 首选“HP LaserJet Pro 400 M401（PCL 6 / PCL XL）”；HL-1218W 仍可选择 brlaser。首次启用自动打印时只打印之后新生成的报告。
        </p>
      </section>
    </el-form>

    <section class="surface">
      <div class="surface-heading"><h2>队列操作</h2></div>
      <div class="physical-queue-row">
        <div>
          <span class="status-label">队列状态</span>
          <strong>{{ configuredQueue ? configuredQueue.state : "尚未创建队列" }}</strong>
          <small v-if="configuredQueue">{{ configuredQueue.device_uri }}</small>
        </div>
        <div class="physical-queue-actions">
          <el-button :disabled="!configuredQueue" :loading="actionLoading === 'test'" @click="testPrint">打印测试页</el-button>
          <el-button
            v-if="configuredQueue?.enabled"
            :disabled="!configuredQueue"
            :loading="actionLoading === 'pause'"
            @click="controlQueue('pause')"
          >暂停队列</el-button>
          <el-button
            v-else
            :disabled="!configuredQueue"
            :loading="actionLoading === 'resume'"
            @click="controlQueue('resume')"
          >恢复队列</el-button>
          <el-button type="danger" plain :disabled="!configuredQueue" @click="deleteQueue">删除队列</el-button>
        </div>
      </div>
    </section>

    <section class="surface reports-table">
      <div class="surface-heading"><h2>最近自动打印任务</h2></div>
      <el-table :data="autoPrint.recent" stripe max-height="280" class="desktop-only">
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="PDF 文件" min-width="320" show-overflow-tooltip>
          <template #default="{ row }">{{ fileName(row.pdf_path) }}</template>
        </el-table-column>
        <el-table-column prop="queue_name" label="队列" width="170" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="jobType(row.status)" effect="light">{{ jobLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="attempts" label="尝试次数" width="100" />
        <el-table-column prop="cups_job_id" label="CUPS 任务" width="170" show-overflow-tooltip />
        <el-table-column prop="last_error" label="错误" min-width="220" show-overflow-tooltip />
        <template #empty><el-empty description="暂无自动打印任务" :image-size="72" /></template>
      </el-table>
      <div class="mobile-only mobile-record-list compact-record-list">
        <article v-for="row in autoPrint.recent" :key="`${row.pdf_path}-${row.updated_at}`" class="mobile-record">
          <div class="mobile-record-heading">
            <div>
              <strong>{{ fileName(row.pdf_path) }}</strong>
              <span>{{ formatTime(row.updated_at) }}</span>
            </div>
            <el-tag :type="jobType(row.status)" effect="light">{{ jobLabel(row.status) }}</el-tag>
          </div>
          <dl class="mobile-record-meta">
            <dt>队列</dt>
            <dd>{{ row.queue_name || "-" }}</dd>
            <dt>尝试次数</dt>
            <dd>{{ row.attempts }}</dd>
            <dt>CUPS 任务</dt>
            <dd>{{ row.cups_job_id || "-" }}</dd>
            <dt>错误</dt>
            <dd :class="{ 'error-text': row.last_error }">{{ row.last_error || "-" }}</dd>
          </dl>
        </article>
        <el-empty v-if="autoPrint.recent.length === 0" description="暂无自动打印任务" :image-size="70" />
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { DocumentChecked, Refresh } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, errorMessage } from "@/api/client";

const formRef = ref();
const loading = ref(false);
const scanning = ref(false);
const saving = ref(false);
const actionLoading = ref("");
const form = reactive({
  enabled: false,
  auto_print: false,
  queue_name: "Physical_Printer",
  device_uri: "",
  driver_profile: "hp_laserjet_m401_pcl6",
  page_size: "A4",
  resolution: "600dpi",
  copies: 1,
  set_default: true
});
const cups = reactive({
  available: false,
  running: false,
  error: "",
  devices: [],
  profiles: [],
  queues: [],
  default_queue: "",
  configured_queue: null
});
const autoPrint = reactive({ counts: {}, recent: [] });
const configuredQueue = computed(() => cups.configured_queue || cups.queues.find((item) => item.name === form.queue_name));
const queueRules = [
  { required: true, message: "请输入队列名称", trigger: "blur" },
  { pattern: /^[A-Za-z0-9._-]{1,64}$/, message: "只能使用英文字母、数字、点、下划线和短横线", trigger: "blur" }
];

function applyPayload(data) {
  Object.assign(form, data.config || {});
  Object.assign(cups, {
    available: false,
    running: false,
    error: "",
    devices: [],
    profiles: [],
    queues: [],
    default_queue: "",
    configured_queue: null,
    ...(data.cups || {})
  });
  Object.assign(autoPrint, { counts: {}, recent: [], ...(data.auto_print || {}) });
}

async function loadConfig() {
  loading.value = true;
  try {
    const { data } = await api.get("/api/physical-printer");
    applyPayload(data);
  } catch (error) {
    ElMessage.error(errorMessage(error, "加载实体打印机配置失败"));
  } finally {
    loading.value = false;
  }
}

async function scanDevices() {
  scanning.value = true;
  try {
    const { data } = await api.post("/api/physical-printer/scan", {});
    Object.assign(cups, data.cups || {});
    ElMessage.success(cups.devices.length ? `发现 ${cups.devices.length} 台打印机` : "扫描完成，未发现打印机");
  } catch (error) {
    ElMessage.error(errorMessage(error, "扫描实体打印机失败"));
  } finally {
    scanning.value = false;
  }
}

function selectDevice(row) {
  form.device_uri = row.uri;
  if (row.recommended_profile) form.driver_profile = row.recommended_profile;
  form.enabled = true;
  ElMessage.success(`已选择 ${row.label}`);
}

function onEnabledChange(value) {
  if (!value) form.auto_print = false;
}

async function saveConfig() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid || saving.value) return;
  if (form.enabled && !form.device_uri) {
    ElMessage.warning("启用实体打印前，请扫描并选择打印机或填写设备 URI");
    return;
  }
  saving.value = true;
  try {
    const { data } = await api.put("/api/physical-printer/config", { ...form });
    Object.assign(form, data.config || {});
    Object.assign(cups, data.cups || {});
    ElMessage.success(data.applied ? "配置已保存，打印队列已创建或更新" : "配置已保存");
    await loadConfig();
  } catch (error) {
    ElMessage.error(errorMessage(error, "保存实体打印机配置失败"));
  } finally {
    saving.value = false;
  }
}

async function testPrint() {
  actionLoading.value = "test";
  try {
    const { data } = await api.post("/api/physical-printer/test", {});
    ElMessage.success(`测试页已提交：${data.job_id || "已进入队列"}`);
  } catch (error) {
    ElMessage.error(errorMessage(error, "测试打印失败"));
  } finally {
    actionLoading.value = "";
  }
}

async function controlQueue(action) {
  actionLoading.value = action;
  try {
    const { data } = await api.post("/api/physical-printer/control", { action });
    Object.assign(cups, data.cups || {});
    ElMessage.success(action === "pause" ? "打印队列已暂停" : "打印队列已恢复");
  } catch (error) {
    ElMessage.error(errorMessage(error, "操作打印队列失败"));
  } finally {
    actionLoading.value = "";
  }
}

async function deleteQueue() {
  try {
    await ElMessageBox.confirm("将删除当前 CUPS 打印队列并关闭自动打印，已生成的 PDF 不会被删除。", "删除打印队列", {
      type: "warning",
      confirmButtonText: "确认删除",
      cancelButtonText: "取消"
    });
  } catch {
    return;
  }
  try {
    await api.delete("/api/physical-printer/queue");
    ElMessage.success("打印队列已删除");
    await loadConfig();
  } catch (error) {
    ElMessage.error(errorMessage(error, "删除打印队列失败"));
  }
}

function profileLabel(value) {
  return cups.profiles.find((item) => item.value === value)?.label || "";
}

function fileName(path) {
  return String(path || "").split(/[\\/]/).pop() || "-";
}

function formatTime(value) {
  if (!value) return "-";
  return new Date(Number(value) * 1000).toLocaleString("zh-CN", { hour12: false });
}

function jobLabel(value) {
  return {
    baseline: "历史基线",
    pending: "待提交",
    submitting: "提交中",
    retry_wait: "等待重试",
    submitted: "已提交",
    exhausted: "失败"
  }[value] || value || "未知";
}

function jobType(value) {
  return value === "submitted" ? "success" : value === "exhausted" ? "danger" : value === "retry_wait" ? "warning" : "info";
}

onMounted(loadConfig);
</script>
