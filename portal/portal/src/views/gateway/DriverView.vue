<template>
  <div class="page-shell driver-page" v-loading="loading">
    <div class="page-heading">
      <div>
        <h1>实体打印驱动</h1>
        <p>导入前仅分析兼容性与安装风险；确认后才安装到板端 CUPS。Windows 驱动和未知可执行文件不会被接受。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="catalogRefreshing" @click="refreshCatalog(false)">刷新型号目录</el-button>
        <el-button :icon="Download" :loading="sourceRefreshing" @click="refreshCatalog(true)">更新软件源</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="loadDrivers">刷新列表</el-button>
      </div>
    </div>

    <div class="configuration-summary driver-summary">
      <div class="summary-item"><span>型号目录</span><strong>{{ catalog.total || 0 }} 条</strong></div>
      <div class="summary-item"><span>已安装型号</span><strong>{{ catalog.installed || 0 }} 条</strong></div>
      <div class="summary-item"><span>软件源可用</span><strong>{{ catalog.available || 0 }} 条</strong></div>
      <div class="summary-item"><span>离线驱动包</span><strong>{{ catalog.offline_pack?.version || "未导入" }}</strong></div>
    </div>

    <section class="surface">
      <div class="surface-heading">
        <div>
          <h2>完整离线驱动包</h2>
          <p class="section-note">仅接受签名的 Noble ARM64 .jvdrv；导入后建立本地只读软件源，不会一次安装全部驱动。</p>
        </div>
      </div>
      <el-upload
        class="driver-upload compact-upload"
        drag
        :auto-upload="false"
        :show-file-list="false"
        accept=".jvdrv"
        :on-change="selectOfflinePack"
      >
        <el-icon class="driver-upload-icon"><UploadFilled /></el-icon>
        <div class="el-upload__text">选择或拖入 JVLEI 离线驱动包</div>
        <template #tip><div class="el-upload__tip">校验签名、系统版本、ARM64架构、软件包白名单和SHA-256后才允许导入。</div></template>
      </el-upload>
      <div v-if="offlineUploading" class="driver-progress"><el-progress :percentage="100" :indeterminate="true" :duration="1" /></div>
      <el-descriptions v-if="offlineStaged" :column="2" border class="driver-descriptions">
        <el-descriptions-item label="版本">{{ offlineStaged.analysis?.version }}</el-descriptions-item>
        <el-descriptions-item label="签名">{{ offlineStaged.analysis?.signed ? "有效" : "无签名" }}</el-descriptions-item>
        <el-descriptions-item label="软件包">{{ offlineStaged.analysis?.package_count }} 个</el-descriptions-item>
        <el-descriptions-item label="型号记录">{{ offlineStaged.analysis?.model_count }} 条</el-descriptions-item>
      </el-descriptions>
      <div v-if="offlineStaged" class="driver-install-actions">
        <el-button type="primary" :icon="DocumentChecked" :loading="offlineInstalling" @click="installOfflinePack">确认导入离线驱动库</el-button>
      </div>
    </section>

    <section class="surface">
      <div class="surface-heading">
        <div>
          <h2>现场导入</h2>
          <p class="section-note">支持 ARM64 或 all 架构的 DEB、PPD / PPD.GZ，以及包含 PPD 和 ARM Filter 的 ZIP、TAR、TGZ、TAR.GZ。</p>
        </div>
      </div>
      <el-upload
        class="driver-upload"
        drag
        :auto-upload="false"
        :show-file-list="false"
        :accept="acceptTypes"
        :on-change="selectFile"
      >
        <el-icon class="driver-upload-icon"><UploadFilled /></el-icon>
        <div class="el-upload__text">选择或拖入 Linux 打印机驱动包</div>
        <template #tip><div class="el-upload__tip">单个文件最大 512 MB。上传只分析，不会立即执行安装。</div></template>
      </el-upload>
      <div v-if="uploading" class="driver-progress"><el-progress :percentage="100" :indeterminate="true" :duration="1" /></div>
    </section>

    <section v-if="staged" class="surface analysis-surface">
      <div class="surface-heading">
        <div>
          <h2>兼容性分析</h2>
          <p class="section-note">{{ staged.filename }} · {{ formatSize(staged.analysis?.size_bytes) }} · SHA-256 {{ staged.analysis?.sha256 }}</p>
        </div>
        <el-tag :type="staged.analysis?.supported ? 'success' : 'danger'" effect="light">
          {{ staged.analysis?.supported ? "可安装" : "不兼容" }}
        </el-tag>
      </div>
      <el-descriptions :column="2" border class="driver-descriptions">
        <el-descriptions-item label="类型">{{ sourceTypeLabel(staged.analysis?.source_type) }}</el-descriptions-item>
        <el-descriptions-item label="架构">{{ architectures || "未发现二进制 Filter" }}</el-descriptions-item>
        <el-descriptions-item label="软件包">{{ staged.analysis?.package || "-" }}</el-descriptions-item>
        <el-descriptions-item label="版本">{{ staged.analysis?.version || "-" }}</el-descriptions-item>
        <el-descriptions-item label="PPD">{{ ppdNames || "未发现" }}</el-descriptions-item>
        <el-descriptions-item label="CUPS Filter">{{ filterNames || "未发现" }}</el-descriptions-item>
        <el-descriptions-item v-if="reasons" label="阻止原因" :span="2"><span class="error-text">{{ reasons }}</span></el-descriptions-item>
        <el-descriptions-item v-if="warnings" label="注意事项" :span="2"><span class="warning-text">{{ warnings }}</span></el-descriptions-item>
      </el-descriptions>
      <div class="driver-install-actions">
        <el-button type="primary" :icon="DocumentChecked" :disabled="!staged.analysis?.supported" :loading="installing" @click="installDriver">
          确认安装驱动
        </el-button>
        <span v-if="hasScripts" class="warning-text">该 DEB 包含 root 安装脚本，安装时会要求二次确认。</span>
      </div>
    </section>

    <section class="surface">
      <div class="surface-heading">
        <div>
          <h2>已审核驱动</h2>
          <p class="section-note">安装后回到“实体打印机配置”页面选择驱动、创建队列并打印测试页。</p>
        </div>
      </div>
      <el-table :data="drivers" stripe max-height="370" class="desktop-only">
        <el-table-column prop="label" label="驱动" min-width="240" show-overflow-tooltip />
        <el-table-column prop="source_type" label="来源" width="110">
          <template #default="{ row }">{{ sourceTypeLabel(row.source_type) }}</template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="150" />
        <el-table-column label="状态" width="115"><template #default="{ row }"><el-tag :type="row.available ? 'success' : 'warning'" effect="light">{{ row.available ? "可用" : "需检查 PPD" }}</el-tag></template></el-table-column>
        <el-table-column label="安装时间" width="180"><template #default="{ row }">{{ formatTime(row.installed_at) }}</template></el-table-column>
        <el-table-column label="操作" width="110" fixed="right"><template #default="{ row }"><el-button link type="warning" @click="rollback(row.backup_id)">回滚</el-button></template></el-table-column>
        <template #empty><el-empty description="暂无现场导入的驱动" :image-size="66" /></template>
      </el-table>
      <div class="mobile-only mobile-record-list compact-record-list">
        <article v-for="row in drivers" :key="row.id" class="mobile-record">
          <div class="mobile-record-heading"><div><strong>{{ row.label }}</strong><span>{{ sourceTypeLabel(row.source_type) }} · {{ row.version || "无版本信息" }}</span></div><el-tag :type="row.available ? 'success' : 'warning'" effect="light">{{ row.available ? "可用" : "需检查" }}</el-tag></div>
          <div class="mobile-record-actions"><el-button type="warning" plain @click="rollback(row.backup_id)">回滚到该备份</el-button></div>
        </article>
        <el-empty v-if="drivers.length === 0" description="暂无现场导入的驱动" :image-size="66" />
      </div>
    </section>

    <section class="surface">
      <div class="surface-heading">
        <div><h2>软件源驱动包</h2><p class="section-note">这里只显示审核白名单；具体型号请在“实体打印机配置”页面搜索。</p></div>
      </div>
      <el-table :data="catalog.packages || []" stripe max-height="330" class="desktop-only">
        <el-table-column prop="label" label="驱动包" min-width="250" show-overflow-tooltip />
        <el-table-column prop="package_name" label="软件包" min-width="210" show-overflow-tooltip />
        <el-table-column prop="model_count" label="型号数" width="95" />
        <el-table-column prop="candidate_version" label="候选版本" width="165" show-overflow-tooltip />
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="row.installed ? 'success' : row.available ? 'info' : 'warning'" effect="light">{{ row.installed ? "已安装" : row.available ? "可下载" : "不可用" }}</el-tag></template></el-table-column>
      </el-table>
    </section>

    <section class="surface">
      <div class="surface-heading"><div><h2>最近安装任务</h2><p class="section-note">APT安装在后台执行，关闭页面不会中断任务。</p></div></div>
      <el-table :data="jobs" stripe max-height="300" class="desktop-only">
        <el-table-column prop="created_at" label="开始时间" width="180"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
        <el-table-column prop="package_name" label="软件包" min-width="230" show-overflow-tooltip />
        <el-table-column prop="summary" label="结果" min-width="260" show-overflow-tooltip />
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="jobType(row.state)" effect="light">{{ jobLabel(row.state) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="100" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="showJobDetail(row)">查看详情</el-button></template></el-table-column>
      </el-table>
      <div class="mobile-only mobile-record-list compact-record-list">
        <article v-for="row in jobs" :key="row.job_id" class="mobile-record">
          <div class="mobile-record-heading"><div><strong>{{ row.package_name || "驱动安装任务" }}</strong><span>{{ formatTime(row.created_at) }}</span></div><el-tag :type="jobType(row.state)" effect="light">{{ jobLabel(row.state) }}</el-tag></div>
          <p class="section-note">{{ row.summary }}</p>
          <div class="mobile-record-actions"><el-button type="primary" plain @click="showJobDetail(row)">查看详情</el-button></div>
        </article>
      </div>
      <el-empty v-if="jobs.length === 0" description="暂无软件源驱动安装任务" :image-size="66" />
    </section>

    <el-dialog v-model="jobDetailVisible" title="驱动安装详情" width="720px">
      <el-descriptions v-if="jobDetail" :column="1" border>
        <el-descriptions-item label="任务编号">{{ jobDetail.job_id }}</el-descriptions-item>
        <el-descriptions-item label="软件包">{{ jobDetail.package_name || "-" }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ jobLabel(jobDetail.state) }}</el-descriptions-item>
        <el-descriptions-item label="结果">{{ jobDetail.summary || "-" }}</el-descriptions-item>
      </el-descriptions>
      <pre class="job-detail-log">{{ jobDetail?.detail || "没有额外日志" }}</pre>
      <template #footer><el-button @click="jobDetailVisible = false">关闭</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { DocumentChecked, Download, Refresh, UploadFilled } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, errorMessage } from "@/api/client";

const loading = ref(false);
const uploading = ref(false);
const installing = ref(false);
const catalogRefreshing = ref(false);
const sourceRefreshing = ref(false);
const offlineUploading = ref(false);
const offlineInstalling = ref(false);
const staged = ref(null);
const offlineStaged = ref(null);
const drivers = ref([]);
const jobs = ref([]);
const jobDetailVisible = ref(false);
const jobDetail = ref(null);
const catalog = ref({ total: 0, installed: 0, available: 0, packages: [], offline_pack: null });
const acceptTypes = ".deb,.ppd,.gz,.zip,.tar,.tgz";
const analysis = computed(() => staged.value?.analysis || {});
const architectures = computed(() => (analysis.value.architectures || []).join(", "));
const ppdNames = computed(() => (analysis.value.ppds || []).map((item) => item.name || item.nick_name).filter(Boolean).join("；"));
const filterNames = computed(() => (analysis.value.filters || []).join("；"));
const reasons = computed(() => (analysis.value.reasons || []).join("；"));
const warnings = computed(() => (analysis.value.warnings || []).join("；"));
const hasScripts = computed(() => (analysis.value.maintainer_scripts || []).length > 0);

function formatSize(value) {
  const size = Number(value || 0);
  return size ? `${(size / 1024 / 1024).toFixed(2)} MB` : "-";
}

function formatTime(value) {
  return value ? new Date(Number(value) * 1000).toLocaleString("zh-CN", { hour12: false }) : "-";
}

function sourceTypeLabel(value) {
  return { deb: "DEB", ppd: "PPD", archive: "压缩包" }[value] || value || "未知";
}

function jobLabel(value) {
  return { queued: "等待", resolving: "解析中", downloading: "下载中", installing: "安装中", indexing: "刷新中", completed: "完成", failed: "失败" }[value] || value || "未知";
}

function jobType(value) {
  return value === "completed" ? "success" : value === "failed" ? "danger" : value === "queued" ? "info" : "warning";
}

function showJobDetail(row) {
  jobDetail.value = row;
  jobDetailVisible.value = true;
}

async function loadDrivers() {
  loading.value = true;
  try {
    const { data } = await api.get("/api/drivers");
    drivers.value = data.drivers || [];
    jobs.value = data.jobs || [];
    catalog.value = data.catalog || catalog.value;
  } catch (error) {
    ElMessage.error(errorMessage(error, "读取驱动列表失败"));
  } finally {
    loading.value = false;
  }
}

async function refreshCatalog(updateSources) {
  const state = updateSources ? sourceRefreshing : catalogRefreshing;
  if (state.value) return;
  if (updateSources) {
    try {
      await ElMessageBox.confirm(
        "将连接当前Ubuntu Noble软件源更新包索引，可能需要数分钟。",
        "更新软件源",
        { type: "info", confirmButtonText: "开始更新", cancelButtonText: "取消" }
      );
    } catch {
      return;
    }
  }
  state.value = true;
  try {
    await api.post("/api/driver-catalog/refresh", { update_sources: updateSources }, { timeout: 10 * 60 * 1000 });
    ElMessage.success(updateSources ? "软件源和型号目录已更新" : "型号目录已刷新");
    await loadDrivers();
  } catch (error) {
    ElMessage.error(errorMessage(error, updateSources ? "更新软件源失败" : "刷新型号目录失败"));
  } finally {
    state.value = false;
  }
}

async function selectOfflinePack(file) {
  const raw = file.raw;
  if (!raw || offlineUploading.value) return;
  if (raw.size > 512 * 1024 * 1024) {
    ElMessage.error("离线驱动包不能超过512 MB");
    return;
  }
  offlineUploading.value = true;
  offlineStaged.value = null;
  try {
    const form = new FormData();
    form.append("driver_pack", raw, raw.name);
    const { data } = await api.post("/api/driver-offline/analyze", form, { timeout: 10 * 60 * 1000 });
    offlineStaged.value = data.upload;
    ElMessage.success("离线驱动包签名和内容校验通过");
  } catch (error) {
    ElMessage.error(errorMessage(error, "离线驱动包校验失败"));
  } finally {
    offlineUploading.value = false;
  }
}

async function installOfflinePack() {
  if (!offlineStaged.value?.id || offlineInstalling.value) return;
  try {
    await ElMessageBox.confirm(
      "将注册为本地只读软件源，不会立即安装全部驱动。",
      "导入离线驱动库",
      { type: "warning", confirmButtonText: "确认导入", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  offlineInstalling.value = true;
  try {
    await api.post("/api/driver-offline/install", { upload_id: offlineStaged.value.id }, { timeout: 10 * 60 * 1000 });
    ElMessage.success("离线驱动库已导入");
    offlineStaged.value = null;
    await refreshCatalog(false);
  } catch (error) {
    ElMessage.error(errorMessage(error, "导入离线驱动库失败"));
  } finally {
    offlineInstalling.value = false;
  }
}

async function selectFile(file) {
  const raw = file.raw;
  if (!raw || uploading.value) return;
  if (raw.size > 512 * 1024 * 1024) {
    ElMessage.error("驱动文件不能超过 512 MB");
    return;
  }
  uploading.value = true;
  staged.value = null;
  try {
    const form = new FormData();
    form.append("driver", raw, raw.name);
    const { data } = await api.post("/api/drivers/analyze", form, { timeout: 8 * 60 * 1000 });
    staged.value = data.upload;
    ElMessage[data.upload.analysis?.supported ? "success" : "warning"](
      data.upload.analysis?.supported ? "驱动分析完成，可以确认安装" : "此文件不能直接安装，请查看阻止原因"
    );
  } catch (error) {
    ElMessage.error(errorMessage(error, "驱动分析失败"));
  } finally {
    uploading.value = false;
  }
}

async function installDriver() {
  let confirmScripts = false;
  if (hasScripts.value) {
    try {
      await ElMessageBox.confirm(
        "该 DEB 包含以 root 权限运行的安装脚本。请确认来源可信且已审核依赖后继续。",
        "驱动包含安装脚本",
        { type: "warning", confirmButtonText: "已审核，继续安装", cancelButtonText: "取消" }
      );
      confirmScripts = true;
    } catch {
      return;
    }
  } else {
    try {
      await ElMessageBox.confirm(
        "将备份当前 CUPS 配置后安装此驱动。安装完成后需要到实体打印机配置页面创建或更新队列。",
        "确认安装驱动",
        { type: "warning", confirmButtonText: "安装", cancelButtonText: "取消" }
      );
    } catch {
      return;
    }
  }
  installing.value = true;
  try {
    await api.post("/api/drivers/install", { upload_id: staged.value.id, confirm_scripts: confirmScripts }, { timeout: 8 * 60 * 1000 });
    ElMessage.success("驱动已安装，CUPS 已刷新");
    staged.value = null;
    await loadDrivers();
  } catch (error) {
    ElMessage.error(errorMessage(error, "驱动安装失败"));
  } finally {
    installing.value = false;
  }
}

async function rollback(backupId) {
  if (!backupId) {
    ElMessage.warning("该驱动没有可用的配置备份");
    return;
  }
  try {
    await ElMessageBox.confirm(
      "将恢复该驱动安装前的 CUPS 队列与驱动注册信息，实体打印队列会短暂重启。",
      "确认回滚驱动",
      { type: "warning", confirmButtonText: "恢复备份", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  try {
    await api.post("/api/drivers/rollback", { backup_id: backupId }, { timeout: 2 * 60 * 1000 });
    ElMessage.success("CUPS 配置已从备份恢复");
    await loadDrivers();
  } catch (error) {
    ElMessage.error(errorMessage(error, "驱动回滚失败"));
  }
}

onMounted(loadDrivers);
</script>

<style scoped lang="scss">
.driver-upload :deep(.el-upload), .driver-upload :deep(.el-upload-dragger) { width: 100%; }
.driver-upload-icon { margin-bottom: 10px; color: #1c8ed1; font-size: 42px; }
.compact-upload :deep(.el-upload-dragger) { padding: 20px; }
.compact-upload .driver-upload-icon { margin-bottom: 4px; font-size: 32px; }
.driver-progress { margin-top: 12px; }
.driver-descriptions { margin-top: 10px; }
.driver-install-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-top: 18px; }
.job-detail-log { max-height: 360px; margin: 14px 0 0; padding: 12px; overflow: auto; border: 1px solid #dcdfe6; background: #f7f8fa; color: #303133; white-space: pre-wrap; overflow-wrap: anywhere; }
.surface-heading > div { min-width: 0; }
.surface-heading .section-note { display: block; margin: 6px 0 0; line-height: 1.5; }
</style>
