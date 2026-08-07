<template>
  <div class="page-shell update-page" v-loading="loading">
    <div class="page-heading">
      <div>
        <h1>软件升级</h1>
        <p>通过设备主动签到获取已签名的升级包。报告采集和上传会在下载期间继续运行。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadStatus">刷新状态</el-button>
        <el-button type="primary" :icon="Search" :loading="checking" :disabled="!status.available || !status.paired" @click="checkUpdate">
          检查更新
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!status.available"
      :title="status.error || '升级代理未运行'"
      description="请检查 jvlei-updater.service。该代理仅监听本机回环地址，不会直接暴露到网络。"
      type="warning"
      :closable="false"
      show-icon
      class="page-alert"
    />

    <section class="surface">
      <div class="surface-heading">
        <div>
          <h2>设备升级状态</h2>
          <p class="section-note">正式升级包必须通过 Ed25519 签名校验；未签名包只能由板端本地测试配置显式允许。</p>
        </div>
        <el-tag :type="status.paired ? 'success' : 'info'" effect="light">{{ status.paired ? "已配对" : "未配对" }}</el-tag>
      </div>
      <div class="configuration-summary update-summary">
        <div class="summary-item"><span>当前版本</span><strong>{{ status.current_version || "未知" }}</strong></div>
        <div class="summary-item"><span>上一版本</span><strong>{{ status.previous_version || "无" }}</strong></div>
        <div class="summary-item"><span>安装策略</span><strong>{{ policyLabel(status.install_policy) }}</strong></div>
        <div class="summary-item"><span>升级中心</span><strong class="update-center-url">{{ status.center_url || "未配置" }}</strong></div>
      </div>
      <div class="update-meta-grid">
        <div><span>代理编号</span><strong>{{ status.agent_id || "尚未配对" }}</strong></div>
        <div><span>上次检查</span><strong>{{ formatTime(status.last_check_at) }}</strong></div>
        <div><span>上次成功</span><strong>{{ formatTime(status.last_success_at) }}</strong></div>
        <div><span>签名限制</span><strong>{{ status.allow_unsigned_packages ? "本地测试可接受未签名包" : "仅接受已签名包" }}</strong></div>
      </div>
    </section>

    <section v-if="!status.paired" class="surface pairing-panel">
      <div class="surface-heading">
        <div>
          <h2>首次配对</h2>
          <p class="section-note">在 Windows 升级中心生成一次性配对码后，在此填写。配对成功会保存独立设备令牌，不使用业务设备编码作为身份。</p>
        </div>
      </div>
      <div class="pairing-row">
        <el-input v-model.trim="pairingCode" maxlength="128" placeholder="例如：A2F6M8..." @keyup.enter="pairDevice" />
        <el-button type="primary" :loading="pairing" :disabled="!status.available || !pairingCode" @click="pairDevice">完成配对</el-button>
      </div>
    </section>

    <section class="surface">
      <div class="surface-heading">
        <div>
          <h2>安装策略</h2>
          <p class="section-note">默认需要在本机管理页面确认安装。只有板端管理员可改为远程允许，升级中心本身不能更改此权限。</p>
        </div>
        <el-button type="primary" plain :loading="savingPolicy" :disabled="!status.available" @click="savePolicy">保存策略</el-button>
      </div>
      <el-radio-group v-model="policy" class="policy-group">
        <el-radio-button value="local_confirm">本机确认安装</el-radio-button>
        <el-radio-button value="remote_allowed">允许中心远程安装</el-radio-button>
      </el-radio-group>
    </section>

    <section class="surface">
      <div class="surface-heading">
        <div>
          <h2>待处理更新</h2>
          <p class="section-note">下载完成后才允许安装；安装失败、服务异常或健康检查版本不匹配时会自动回滚到上一版本。</p>
        </div>
        <div class="page-actions">
          <el-button :icon="Download" :loading="downloading" :disabled="!canDownload" @click="downloadUpdate">下载升级包</el-button>
          <el-button type="primary" :icon="CircleCheck" :loading="installing" :disabled="!canInstall" @click="installUpdate">安装更新</el-button>
          <el-button type="warning" plain :icon="RefreshLeft" :loading="rollingBack" :disabled="!canRollback" @click="rollback">回滚上一版本</el-button>
        </div>
      </div>

      <el-descriptions :column="2" border class="update-descriptions">
        <el-descriptions-item label="任务状态">{{ assignmentStatus }}</el-descriptions-item>
        <el-descriptions-item label="下载状态">{{ downloadStatus }}</el-descriptions-item>
        <el-descriptions-item label="目标版本">{{ targetVersion }}</el-descriptions-item>
        <el-descriptions-item label="包签名">{{ packageSigned }}</el-descriptions-item>
        <el-descriptions-item label="发布说明" :span="2">{{ releaseNotes || "暂无" }}</el-descriptions-item>
        <el-descriptions-item v-if="status.last_error" label="最近错误" :span="2">
          <span class="error-text">{{ status.last_error }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { CircleCheck, Download, Refresh, RefreshLeft, Search } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, errorMessage } from "@/api/client";

const loading = ref(false);
const checking = ref(false);
const pairing = ref(false);
const savingPolicy = ref(false);
const downloading = ref(false);
const installing = ref(false);
const rollingBack = ref(false);
const pairingCode = ref("");
const policy = ref("local_confirm");
const status = ref({ available: false, paired: false, assignment: null, download: null });

const assignment = computed(() => status.value.assignment || null);
const downloaded = computed(() => status.value.download || null);
const canDownload = computed(() => Boolean(status.value.available && assignment.value?.package && !downloaded.value?.ready));
const canInstall = computed(() => Boolean(status.value.available && downloaded.value?.ready));
const canRollback = computed(() => Boolean(status.value.available && status.value.previous_version));
const targetVersion = computed(() => downloaded.value?.manifest?.version || assignment.value?.package?.version || "暂无待处理更新");
const releaseNotes = computed(() => downloaded.value?.manifest?.release_notes || "");
const packageSigned = computed(() => {
  if (downloaded.value?.ready) return downloaded.value.signed ? "已验证 Ed25519 签名" : "未签名（本地测试）";
  if (assignment.value?.package) return assignment.value.package.signed ? "已签名，尚未下载" : "未签名，尚未下载";
  return "-";
});
const assignmentStatus = computed(() => assignment.value ? `${assignment.value.action === "install" ? "下发安装" : "下发下载"} · ${assignment.value.status || "等待设备领取"}` : "暂无任务");
const downloadStatus = computed(() => downloaded.value?.ready ? `已验证 · ${formatTime(downloaded.value.downloaded_at)}` : "未下载");

function policyLabel(value) {
  return value === "remote_allowed" ? "允许远程安装" : "本机确认";
}

function formatTime(value) {
  return value ? new Date(Number(value) * 1000).toLocaleString("zh-CN", { hour12: false }) : "-";
}

async function loadStatus() {
  loading.value = true;
  try {
    const { data } = await api.get("/api/update/status");
    status.value = data;
    policy.value = data.install_policy || "local_confirm";
  } catch (error) {
    ElMessage.error(errorMessage(error, "读取升级状态失败"));
  } finally {
    loading.value = false;
  }
}

async function pairDevice() {
  pairing.value = true;
  try {
    const { data } = await api.post("/api/update/pair", { pairing_code: pairingCode.value });
    status.value = { ...status.value, ...data, available: true };
    pairingCode.value = "";
    ElMessage.success("设备已完成配对");
    await loadStatus();
  } catch (error) {
    ElMessage.error(errorMessage(error, "设备配对失败"));
  } finally {
    pairing.value = false;
  }
}

async function checkUpdate() {
  checking.value = true;
  try {
    const { data } = await api.post("/api/update/check", {});
    status.value = { ...status.value, ...data, available: true };
    ElMessage.success(data.assignment ? "发现已下发的更新任务" : "当前没有可用更新");
  } catch (error) {
    ElMessage.error(errorMessage(error, "检查更新失败"));
  } finally {
    checking.value = false;
  }
}

async function savePolicy() {
  savingPolicy.value = true;
  try {
    const { data } = await api.put("/api/update/policy", { install_policy: policy.value });
    status.value = { ...status.value, ...data, available: true };
    ElMessage.success("安装策略已保存");
  } catch (error) {
    ElMessage.error(errorMessage(error, "保存安装策略失败"));
  } finally {
    savingPolicy.value = false;
  }
}

async function downloadUpdate() {
  downloading.value = true;
  try {
    const { data } = await api.post("/api/update/download", {}, { timeout: 10 * 60 * 1000 });
    status.value = { ...status.value, ...data, available: true };
    ElMessage.success("升级包已下载并完成签名与哈希校验");
  } catch (error) {
    ElMessage.error(errorMessage(error, "下载升级包失败"));
  } finally {
    downloading.value = false;
  }
}

async function installUpdate() {
  try {
    await ElMessageBox.confirm(
      `即将安装 ${targetVersion.value}。网页和采集服务会短暂重启，报告配置和历史数据不会被覆盖。`,
      "确认安装更新",
      { type: "warning", confirmButtonText: "安装并重启服务", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  installing.value = true;
  try {
    const { data } = await api.post("/api/update/install", {}, { timeout: 12 * 60 * 1000 });
    status.value = { ...status.value, ...data, available: true };
    ElMessage.success("更新已安装并通过健康检查");
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
    ElMessage.success("已恢复上一版本");
  } catch (error) {
    ElMessage.error(errorMessage(error, "回滚失败"));
  } finally {
    rollingBack.value = false;
  }
}

onMounted(loadStatus);
</script>

<style scoped lang="scss">
.update-summary {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.surface-heading > div { min-width: 0; }

.surface-heading .section-note {
  display: block;
  margin: 6px 0 0;
  line-height: 1.5;
}

.update-center-url {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.update-meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;

  > div {
    min-width: 0;
    padding: 12px;
    border: 1px solid #e5edf5;
    background: #f9fbfd;
  }

  span, strong {
    display: block;
  }

  span { color: #6e7f91; font-size: 12px; }
  strong { margin-top: 5px; overflow-wrap: anywhere; color: #23354d; }
}

.pairing-row {
  display: flex;
  max-width: 600px;
  gap: 12px;
}

.policy-group { margin-top: 4px; }
.update-descriptions { margin-top: 10px; }

@media (max-width: 980px) {
  .update-summary, .update-meta-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 640px) {
  .update-summary, .update-meta-grid { grid-template-columns: 1fr; }
  .pairing-row { flex-direction: column; }
}
</style>
