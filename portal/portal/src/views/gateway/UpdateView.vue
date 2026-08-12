<template>
  <div class="page-shell update-page" v-loading="loading">
    <div class="page-heading">
      <div>
        <h1>软件升级</h1>
        <p>通过公司升级服务检查、下载和安装新版本。开机检查一次，也可以在此手动检查。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadStatus">刷新状态</el-button>
        <el-button type="primary" :icon="Search" :loading="checking" :disabled="!status.available || !status.enabled" @click="checkUpdate">
          检查更新
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!status.available"
      :title="status.error || '升级代理未运行'"
      description="请检查 jvlei-updater.service。报告采集和上传服务不受影响。"
      type="warning"
      :closable="false"
      show-icon
      class="page-alert"
    />

    <el-alert
      title="当前为测试阶段升级包"
      description="升级包暂未启用数字签名，但会强制校验文件大小、ZIP CRC 和内部 payload SHA-256。"
      type="warning"
      :closable="false"
      show-icon
      class="page-alert"
    />

    <section class="surface">
      <div class="surface-heading">
        <div>
          <h2>设备升级状态</h2>
          <p class="section-note">自动升级由公司升级策略控制；策略关闭时需要在本页手动下载安装。</p>
        </div>
        <el-tag :type="status.available ? 'success' : 'info'" effect="light">
          {{ status.available ? "代理正常" : "代理离线" }}
        </el-tag>
      </div>
      <div class="configuration-summary update-summary">
        <div class="summary-item"><span>当前版本</span><strong>{{ status.current_version || "未知" }}</strong></div>
        <div class="summary-item"><span>版本ID</span><strong>{{ status.current_version_id || "未记录" }}</strong></div>
        <div class="summary-item"><span>上一版本</span><strong>{{ status.previous_version || "无" }}</strong></div>
        <div class="summary-item"><span>应用编码</span><strong>{{ status.app_code || "linux" }}</strong></div>
      </div>
      <div class="update-meta-grid">
        <div><span>当前网卡</span><strong>{{ status.network?.interface || "-" }}</strong></div>
        <div><span>当前IP</span><strong>{{ status.network?.ip || "-" }}</strong></div>
        <div><span>当前MAC</span><strong>{{ status.network?.mac || "-" }}</strong></div>
        <div><span>运行平台</span><strong>{{ status.platform || "linux-arm64" }}</strong></div>
        <div><span>上次检查</span><strong>{{ formatTime(status.last_check_at) }}</strong></div>
        <div><span>上次成功</span><strong>{{ formatTime(status.last_success_at) }}</strong></div>
        <div><span>待补发上报</span><strong>{{ status.pending_reports || 0 }}</strong></div>
        <div><span>安装状态</span><strong>{{ operationStatus }}</strong></div>
      </div>
    </section>

    <section class="surface">
      <div class="surface-heading">
        <div>
          <h2>升级配置</h2>
        </div>
        <el-button type="primary" plain :loading="savingConfig" :disabled="!status.available" @click="saveConfig">
          保存并同步
        </el-button>
      </div>
      <el-form label-position="top" class="company-config-form">
        <el-form-item label="启用在线升级">
          <el-switch v-model="companyForm.enabled" inline-prompt active-text="开启" inactive-text="关闭" />
        </el-form-item>
        <el-form-item label="开机检查更新">
          <el-switch v-model="companyForm.boot_check" inline-prompt active-text="开启" inactive-text="关闭" />
        </el-form-item>
        <el-form-item label="应用编码（appCode）">
          <el-input v-model.trim="companyForm.app_code" maxlength="128" placeholder="例如：linux" />
          <div class="field-tip">必须与升级中心的应用编码和升级包清单一致。</div>
        </el-form-item>
        <el-form-item label="运行平台">
          <el-select v-model="companyForm.platform" class="full-width">
            <el-option label="Linux ARM64" value="linux-arm64" />
          </el-select>
        </el-form-item>
        <el-form-item label="系统升级中心" class="full-row">
          <el-input v-model.trim="companyForm.center_url" maxlength="512" placeholder="例如：http://192.168.112.229:28080" />
        </el-form-item>
        <el-form-item label="医院编码">
          <el-input v-model.trim="companyForm.hospital_code" maxlength="128" placeholder="例如：tejian01" />
        </el-form-item>
        <el-form-item label="医院ID（选填）">
          <el-input v-model.trim="companyForm.hospital_id" maxlength="128" />
        </el-form-item>
        <el-form-item label="院区编码（选填）">
          <el-input v-model.trim="companyForm.hospital_area_code" maxlength="128" />
        </el-form-item>
        <el-form-item label="院区ID（选填）">
          <el-input v-model.trim="companyForm.hospital_area_id" maxlength="128" />
        </el-form-item>
        <el-form-item label="科室编码（选填）">
          <el-input v-model.trim="companyForm.dept_code" maxlength="128" />
        </el-form-item>
        <el-form-item label="科室ID（选填）">
          <el-input v-model.trim="companyForm.dept_id" maxlength="128" />
        </el-form-item>
      </el-form>
      <div class="sync-result">
        <el-tag :type="status.last_terminal_report_error ? 'danger' : status.last_terminal_report_at ? 'success' : 'info'" effect="light">
          {{ terminalSyncStatus }}
        </el-tag>
        <span v-if="status.last_terminal_report_error" class="error-text">{{ status.last_terminal_report_error }}</span>
      </div>
      <el-descriptions :column="descriptionColumns" border class="terminal-descriptions">
        <el-descriptions-item label="终端名称">{{ status.terminal_name || "-" }}</el-descriptions-item>
        <el-descriptions-item label="操作系统">{{ status.os_version || "-" }}</el-descriptions-item>
        <el-descriptions-item label="终端IP">{{ status.network?.ip || "-" }}</el-descriptions-item>
        <el-descriptions-item label="终端MAC">{{ status.network?.mac || "-" }}</el-descriptions-item>
      </el-descriptions>
    </section>

    <section class="surface">
      <div class="surface-heading">
        <div>
          <h2>待处理更新</h2>
          <p class="section-note">安装前会等待正在上传的报告，备份现场配置，并通过软链接原子切换版本。</p>
        </div>
        <div class="page-actions">
          <el-button :icon="Download" :loading="downloading" :disabled="!canDownload" @click="downloadUpdate">下载升级包</el-button>
          <el-button type="primary" :icon="CircleCheck" :loading="installing" :disabled="!canInstall" @click="installUpdate">安装更新</el-button>
          <el-button type="warning" plain :icon="RefreshLeft" :loading="rollingBack" :disabled="!canRollback" @click="rollback">回滚上一版本</el-button>
        </div>
      </div>

      <el-descriptions :column="descriptionColumns" border class="update-descriptions">
        <el-descriptions-item label="策略状态">{{ strategyStatus }}</el-descriptions-item>
        <el-descriptions-item label="下载状态">{{ downloadStatus }}</el-descriptions-item>
        <el-descriptions-item label="目标版本">{{ targetVersion }}</el-descriptions-item>
        <el-descriptions-item label="目标版本ID">{{ update?.version_id || "-" }}</el-descriptions-item>
        <el-descriptions-item label="升级记录ID">{{ update?.record_id || "-" }}</el-descriptions-item>
        <el-descriptions-item label="包大小">{{ formatBytes(update?.package_size) }}</el-descriptions-item>
        <el-descriptions-item label="发布说明" :span="2">{{ update?.release_note || "暂无" }}</el-descriptions-item>
        <el-descriptions-item v-if="status.last_error" label="最近错误" :span="2">
          <span class="error-text">{{ status.last_error }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { CircleCheck, Download, Refresh, RefreshLeft, Search } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, errorMessage } from "@/api/client";

const loading = ref(false);
const checking = ref(false);
const savingConfig = ref(false);
const downloading = ref(false);
const installing = ref(false);
const rollingBack = ref(false);
const mobileLayout = ref(window.innerWidth <= 640);
const companyForm = reactive({
  enabled: true,
  boot_check: true,
  center_url: "",
  app_code: "linux",
  platform: "linux-arm64",
  hospital_code: "",
  hospital_id: "",
  hospital_area_code: "",
  hospital_area_id: "",
  dept_code: "",
  dept_id: ""
});
const formLoaded = ref(false);
const status = ref({ available: false, update: null, download: null, network: {} });

const update = computed(() => status.value.update || null);
const downloaded = computed(() => status.value.download || null);
const canDownload = computed(() => Boolean(status.value.available && status.value.enabled && update.value && !downloaded.value?.ready && !status.value.installing));
const canInstall = computed(() => Boolean(status.value.available && status.value.enabled && downloaded.value?.ready && !status.value.installing));
const canRollback = computed(() => Boolean(status.value.available && status.value.previous_version && !status.value.installing));
const targetVersion = computed(() => update.value?.version || downloaded.value?.manifest?.server_version || "暂无可用更新");
const strategyStatus = computed(() => {
  if (!update.value) return "当前没有可用更新";
  return update.value.auto_upgrade ? "公司策略：自动升级" : "公司策略：等待现场确认";
});
const downloadStatus = computed(() => downloaded.value?.ready ? `已校验 · ${formatTime(downloaded.value.downloaded_at)}` : "未下载");
const operationStatus = computed(() => {
  if (!status.value.installing) return "空闲";
  if (status.value.operation === "rollback") return "正在回滚";
  if (status.value.operation === "auto_upgrade") return "正在自动升级";
  return "正在安装";
});
const descriptionColumns = computed(() => mobileLayout.value ? 1 : 2);
const terminalSyncStatus = computed(() => {
  if (!status.value.enabled) return "在线升级已关闭";
  if (status.value.last_terminal_report_error) return "终端信息同步失败";
  if (status.value.last_terminal_report_at) return `已同步 · ${formatTime(status.value.last_terminal_report_at)}`;
  return "尚未同步";
});
let statusTimer = 0;

function updateViewport() {
  mobileLayout.value = window.innerWidth <= 640;
}

function formatTime(value) {
  return value ? new Date(Number(value) * 1000).toLocaleString("zh-CN", { hour12: false }) : "-";
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (!size) return "-";
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(2)} MB`;
}

async function loadStatus(silent = false) {
  if (!silent) loading.value = true;
  try {
    const { data } = await api.get("/api/update/status");
    status.value = data;
    if (!silent || !formLoaded.value) {
      Object.assign(companyForm, {
        enabled: data.enabled !== false,
        boot_check: data.boot_check !== false,
        center_url: data.center_url || "",
        app_code: data.app_code || "linux",
        platform: data.platform || "linux-arm64",
        ...(data.organization || {})
      });
      formLoaded.value = true;
    }
  } catch (error) {
    if (!silent) ElMessage.error(errorMessage(error, "读取升级状态失败"));
  } finally {
    if (!silent) loading.value = false;
  }
}

async function saveConfig() {
  savingConfig.value = true;
  try {
    if (!companyForm.hospital_code) {
      ElMessage.warning("请填写医院编码");
      return;
    }
    if (!companyForm.app_code) {
      ElMessage.warning("请填写应用编码（appCode）");
      return;
    }
    const { enabled, boot_check, center_url, app_code, platform, ...organization } = companyForm;
    const settings = { enabled, boot_check, center_url, app_code, platform };
    const { data } = await api.put("/api/update/config", { settings, organization });
    status.value = { ...status.value, ...data, available: true };
    Object.assign(companyForm, {
      enabled: data.enabled,
      boot_check: data.boot_check,
      center_url: data.center_url || center_url,
      app_code: data.app_code || app_code,
      platform: data.platform || platform,
      ...(data.organization || {})
    });
    if (!data.enabled) {
      ElMessage.success("升级配置已保存，在线升级已关闭");
      return;
    }
    if (data.last_terminal_report_error) {
      ElMessage.warning("升级配置已保存，但终端信息同步失败，可稍后再次保存或检查更新");
    } else {
      ElMessage.success("升级配置已保存，终端信息已同步");
    }
  } catch (error) {
    ElMessage.error(errorMessage(error, "保存或同步升级配置失败"));
  } finally {
    savingConfig.value = false;
  }
}

async function checkUpdate() {
  checking.value = true;
  try {
    const { data } = await api.post("/api/update/check", {});
    status.value = { ...status.value, ...data, available: true };
    ElMessage.success(data.installing ? "公司策略已启动自动升级" : data.update ? "发现可用更新" : "当前已经是适用版本");
  } catch (error) {
    ElMessage.error(errorMessage(error, "检查更新失败"));
  } finally {
    checking.value = false;
  }
}

async function downloadUpdate() {
  downloading.value = true;
  try {
    const { data } = await api.post("/api/update/download", {}, { timeout: 10 * 60 * 1000 });
    status.value = { ...status.value, ...data, available: true };
    ElMessage.success("升级包已通过大小、ZIP CRC 和 SHA-256 校验");
  } catch (error) {
    ElMessage.error(errorMessage(error, "下载升级包失败"));
  } finally {
    downloading.value = false;
  }
}

async function installUpdate() {
  try {
    await ElMessageBox.confirm(
      `即将安装 ${targetVersion.value}。网页和采集服务会短暂停止，现场配置和报告数据不会被覆盖。`,
      "确认安装更新",
      { type: "warning", confirmButtonText: "安装更新", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  installing.value = true;
  try {
    const { data } = await api.post("/api/update/install", {}, { timeout: 12 * 60 * 1000 });
    status.value = { ...status.value, ...data, available: true };
    ElMessage.success("安装任务已启动，服务重启期间页面会短暂离线");
  } catch (error) {
    ElMessage.error(errorMessage(error, "安装失败，系统已尝试自动回滚"));
  } finally {
    installing.value = false;
  }
}

async function rollback() {
  try {
    await ElMessageBox.confirm(
      `将恢复到 ${status.value.previous_version}，网页和采集服务会短暂重启。`,
      "确认回滚",
      { type: "warning", confirmButtonText: "恢复上一版本", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  rollingBack.value = true;
  try {
    const { data } = await api.post("/api/update/rollback", {}, { timeout: 8 * 60 * 1000 });
    status.value = { ...status.value, ...data, available: true };
    ElMessage.success("回滚任务已启动，服务重启期间页面会短暂离线");
  } catch (error) {
    ElMessage.error(errorMessage(error, "回滚失败"));
  } finally {
    rollingBack.value = false;
  }
}

onMounted(() => {
  window.addEventListener("resize", updateViewport);
  loadStatus();
  statusTimer = window.setInterval(() => loadStatus(true), 3000);
});
onBeforeUnmount(() => {
  window.clearInterval(statusTimer);
  window.removeEventListener("resize", updateViewport);
});
</script>

<style scoped lang="scss">
.update-summary { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.surface-heading > div { min-width: 0; }
.surface-heading .section-note { display: block; margin: 6px 0 0; line-height: 1.5; }
.update-meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;

  > div { min-width: 0; padding: 12px; border: 1px solid #e5edf5; background: #f9fbfd; }
  span, strong { display: block; }
  span { color: #6e7f91; font-size: 12px; }
  strong { margin-top: 5px; overflow-wrap: anywhere; color: #23354d; }
}
.update-descriptions { margin-top: 10px; }
.company-config-form {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0 16px;

  .full-row { grid-column: 1 / -1; }
}
.sync-result { display: flex; align-items: center; gap: 12px; min-height: 28px; }
.terminal-descriptions { margin-top: 14px; }
.full-width { width: 100%; }
.field-tip { margin-top: 5px; color: #7b8998; font-size: 12px; line-height: 1.4; }
@media (max-width: 980px) {
  .update-summary, .update-meta-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .company-config-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .update-summary, .update-meta-grid { grid-template-columns: 1fr; }
  .company-config-form { grid-template-columns: 1fr; }
  .company-config-form .full-row { grid-column: auto; }
  .sync-result { align-items: flex-start; flex-direction: column; }
}
</style>
