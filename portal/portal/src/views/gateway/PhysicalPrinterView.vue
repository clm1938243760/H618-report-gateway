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
          <template #default="{ row }">{{ recommendedLabel(row) }}</template>
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
            <dd>{{ recommendedLabel(row) }}</dd>
          </dl>
          <div class="mobile-record-actions">
            <el-button type="primary" @click="selectDevice(row)">选择此打印机</el-button>
          </div>
        </article>
        <el-empty v-if="cups.devices.length === 0" description="未发现实体打印机" :image-size="70" />
      </div>
    </section>

    <section class="surface driver-catalog-surface">
      <div class="surface-heading">
        <div>
          <h2>选择实体打印机型号</h2>
          <p class="section-note">型号目录来自 Ubuntu Noble ARM64 软件源；选择型号只生成受控安装计划，不执行网页输入的命令。</p>
        </div>
        <el-tag effect="plain">{{ catalog.total }} 个型号</el-tag>
      </div>
      <div class="catalog-toolbar">
        <el-input
          v-model.trim="catalogQuery"
          clearable
          :prefix-icon="Search"
          placeholder="输入厂商或型号，例如 Brother HL-1218W"
          @keyup.enter="searchCatalog(1)"
        />
        <el-select v-model="catalogVendor" clearable filterable placeholder="全部厂商">
          <el-option v-for="vendor in catalog.vendors" :key="vendor" :label="vendor" :value="vendor" />
        </el-select>
        <el-select v-model="catalogStatus" clearable placeholder="全部状态">
          <el-option label="已实机验证" value="verified" />
          <el-option label="已安装" value="installed" />
          <el-option label="软件源可用" value="available" />
          <el-option label="不可用" value="unavailable" />
          <el-option label="通用驱动" value="generic" />
        </el-select>
        <el-button type="primary" :icon="Search" :loading="catalogLoading" @click="searchCatalog(1)">查询</el-button>
      </div>

      <el-alert
        v-if="selectedCatalogModel"
        :title="`已选：${selectedCatalogModel.manufacturer} ${selectedCatalogModel.model}`"
        :description="selectedCatalogModel.installed ? '驱动已安装，保存配置时将创建或更新CUPS队列。' : '该驱动尚未安装，请先生成安装计划。'"
        :type="selectedCatalogModel.installed ? 'success' : 'warning'"
        :closable="false"
        show-icon
        class="catalog-selection-alert"
      />

      <el-table :data="catalog.items" stripe max-height="390" class="desktop-only" v-loading="catalogLoading">
        <el-table-column label="厂商/型号" min-width="290" show-overflow-tooltip>
          <template #default="{ row }"><strong>{{ row.manufacturer }}</strong> {{ row.model }}</template>
        </el-table-column>
        <el-table-column label="协议" min-width="155" show-overflow-tooltip>
          <template #default="{ row }">{{ (row.protocols || []).join("、") }}</template>
        </el-table-column>
        <el-table-column prop="package_name" label="软件包" min-width="190" show-overflow-tooltip>
          <template #default="{ row }">{{ row.package_name || "系统通用" }}</template>
        </el-table-column>
        <el-table-column label="等级" width="125">
          <template #default="{ row }"><el-tag :type="verificationType(row)" effect="light">{{ verificationLabel(row) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="状态" width="105">
          <template #default="{ row }">{{ row.installed ? "已安装" : row.available ? "可下载" : "不可用" }}</template>
        </el-table-column>
        <el-table-column label="操作" width="112" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :disabled="!row.available" @click="chooseOrPlan(row)">
              {{ row.installed && row.cups_model ? "选择" : "安装" }}
            </el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="没有匹配的打印机型号" :image-size="70" /></template>
      </el-table>

      <div class="mobile-only mobile-record-list compact-record-list">
        <article v-for="row in catalog.items" :key="row.model_id" class="mobile-record">
          <div class="mobile-record-heading">
            <div><strong>{{ row.manufacturer }} {{ row.model }}</strong><span>{{ row.package_name || "系统通用" }}</span></div>
            <el-tag :type="verificationType(row)" effect="light">{{ verificationLabel(row) }}</el-tag>
          </div>
          <dl class="mobile-record-meta"><dt>协议</dt><dd>{{ (row.protocols || []).join("、") }}</dd><dt>状态</dt><dd>{{ row.installed ? "已安装" : row.available ? "可下载" : "不可用" }}</dd></dl>
          <div class="mobile-record-actions"><el-button type="primary" plain :disabled="!row.available" @click="chooseOrPlan(row)">{{ row.installed && row.cups_model ? "选择驱动" : "查看安装计划" }}</el-button></div>
        </article>
      </div>
      <el-pagination
        v-if="catalog.total > catalog.page_size"
        v-model:current-page="catalog.page"
        :page-size="catalog.page_size"
        :total="catalog.total"
        layout="prev, pager, next, total"
        class="catalog-pagination"
        @current-change="searchCatalog"
      />
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
                v-if="selectedCatalogModel?.installed && selectedCatalogModel?.cups_model"
                :label="`${selectedCatalogModel.manufacturer} ${selectedCatalogModel.model}`"
                :value="`catalog:${selectedCatalogModel.model_id}`"
              />
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
            v-if="selectedCatalogModel"
            type="success"
            plain
            :loading="validationLoading === 'passed'"
            @click="validateSelectedDriver('passed')"
          >内容正常</el-button>
          <el-button
            v-if="selectedCatalogModel"
            type="warning"
            plain
            :loading="validationLoading === 'failed'"
            @click="validateSelectedDriver('failed')"
          >内容异常</el-button>
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

    <el-dialog v-model="planDialogVisible" title="驱动安装计划" width="620px" destroy-on-close>
      <el-descriptions v-if="installPlan" :column="1" border>
        <el-descriptions-item label="型号">{{ installPlan.model?.manufacturer }} {{ installPlan.model?.model }}</el-descriptions-item>
        <el-descriptions-item label="软件包">{{ installPlan.package_name || "无需安装" }}</el-descriptions-item>
        <el-descriptions-item label="候选版本">{{ installPlan.candidate_version || "已安装" }}</el-descriptions-item>
        <el-descriptions-item label="安装来源">{{ installPlan.source === "offline" ? "JVLEI离线驱动包" : installPlan.source === "installed" ? "系统已安装" : "Ubuntu Noble软件源" }}</el-descriptions-item>
        <el-descriptions-item label="依赖">{{ (installPlan.dependencies || []).join("、") || "无新增依赖" }}</el-descriptions-item>
        <el-descriptions-item label="下载量">{{ formatBytes(installPlan.download_bytes) }}</el-descriptions-item>
        <el-descriptions-item label="新增占用">{{ formatBytes(installPlan.install_bytes) }}</el-descriptions-item>
        <el-descriptions-item label="可用空间">{{ formatBytes(installPlan.free_bytes) }}</el-descriptions-item>
      </el-descriptions>
      <el-progress v-if="installJob && !jobFinished" :percentage="jobPercentage" :indeterminate="installJob.state === 'installing'" class="catalog-job-progress" />
      <p v-if="installJob" :class="installJob.state === 'failed' ? 'error-text' : 'section-note'">{{ installJob.summary }}</p>
      <template #footer>
        <el-button @click="planDialogVisible = false">关闭</el-button>
        <el-button v-if="installPlan?.required && !installJob" type="primary" :loading="installStarting" @click="startDriverInstall">确认下载并安装</el-button>
        <el-button v-if="installJob?.state === 'completed'" type="primary" @click="finishInstalledDriver">返回选择型号</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { DocumentChecked, Refresh, Search } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, errorMessage } from "@/api/client";

const formRef = ref();
const loading = ref(false);
const scanning = ref(false);
const saving = ref(false);
const actionLoading = ref("");
const catalogLoading = ref(false);
const catalogQuery = ref("");
const catalogVendor = ref("");
const catalogStatus = ref("");
const selectedCatalogModel = ref(null);
const installPlan = ref(null);
const installJob = ref(null);
const installStarting = ref(false);
const validationLoading = ref("");
const planDialogVisible = ref(false);
let jobTimer = 0;
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
const catalog = reactive({ items: [], total: 0, page: 1, page_size: 30, vendors: [], updated_at: 0 });
const autoPrint = reactive({ counts: {}, recent: [] });
const configuredQueue = computed(() => cups.configured_queue || cups.queues.find((item) => item.name === form.queue_name));
const jobFinished = computed(() => ["completed", "failed"].includes(installJob.value?.state));
const jobPercentage = computed(() => ({ queued: 5, resolving: 18, downloading: 40, installing: 68, indexing: 88, completed: 100, failed: 100 }[installJob.value?.state] || 0));
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
  if (data.cups?.selected_catalog_model) selectedCatalogModel.value = data.cups.selected_catalog_model;
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
  const recommendation = row.catalog_recommendations?.[0];
  if (recommendation) {
    selectedCatalogModel.value = recommendation;
    form.driver_profile = recommendation.installed && recommendation.cups_model
      ? `catalog:${recommendation.model_id}`
      : "";
  } else if (row.recommended_profile) {
    form.driver_profile = row.recommended_profile;
  }
  form.enabled = true;
  ElMessage.success(recommendation ? `已选择 ${row.label}，推荐 ${recommendation.model}` : `已选择 ${row.label}`);
}

async function searchCatalog(page = 1) {
  catalogLoading.value = true;
  try {
    const { data } = await api.get("/api/driver-catalog", {
      params: {
        query: catalogQuery.value,
        vendor: catalogVendor.value,
        status: catalogStatus.value,
        page,
        page_size: catalog.page_size
      }
    });
    Object.assign(catalog, data.summary || {}, {
      items: data.items || [],
      total: data.total || 0,
      page: data.page || 1,
      page_size: data.page_size || 30
    });
  } catch (error) {
    ElMessage.error(errorMessage(error, "读取打印机型号目录失败"));
  } finally {
    catalogLoading.value = false;
  }
}

async function chooseOrPlan(row) {
  selectedCatalogModel.value = row;
  if (row.installed && row.cups_model) {
    form.driver_profile = `catalog:${row.model_id}`;
    form.enabled = true;
    ElMessage.success("驱动已选择，请确认队列参数后保存应用");
    return;
  }
  installPlan.value = null;
  installJob.value = null;
  try {
    const { data } = await api.post("/api/driver-packages/plan", { model_id: row.model_id }, { timeout: 3 * 60 * 1000 });
    installPlan.value = data.plan;
    planDialogVisible.value = true;
  } catch (error) {
    ElMessage.error(errorMessage(error, "生成驱动安装计划失败"));
  }
}

async function startDriverInstall() {
  if (!installPlan.value?.model?.model_id || installStarting.value) return;
  installStarting.value = true;
  try {
    const { data } = await api.post("/api/driver-packages/install", { model_id: installPlan.value.model.model_id });
    installJob.value = data.job;
    pollInstallJob();
  } catch (error) {
    ElMessage.error(errorMessage(error, "启动驱动安装失败"));
  } finally {
    installStarting.value = false;
  }
}

async function pollInstallJob() {
  window.clearTimeout(jobTimer);
  if (!installJob.value?.job_id || jobFinished.value) return;
  try {
    const { data } = await api.get(`/api/driver-jobs/${installJob.value.job_id}`);
    installJob.value = data.job;
    if (installJob.value.state === "completed") {
      ElMessage.success("驱动安装完成，请选择具体型号并创建队列");
      await searchCatalog(catalog.page);
      return;
    }
    if (installJob.value.state === "failed") {
      ElMessage.error(installJob.value.summary || "驱动安装失败");
      return;
    }
  } catch (error) {
    ElMessage.error(errorMessage(error, "读取驱动安装进度失败"));
    return;
  }
  jobTimer = window.setTimeout(pollInstallJob, 1200);
}

async function finishInstalledDriver() {
  planDialogVisible.value = false;
  await searchCatalog(1);
  const original = installPlan.value?.model;
  const refreshed = catalog.items.find((item) => item.model_id === original?.model_id);
  if (refreshed?.installed && refreshed.cups_model) {
    selectedCatalogModel.value = refreshed;
    form.driver_profile = `catalog:${refreshed.model_id}`;
    form.enabled = true;
  }
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

async function validateSelectedDriver(result) {
  const modelId = selectedCatalogModel.value?.model_id;
  if (!modelId || validationLoading.value) return;
  let notes = "测试页文字、图形和分页正常";
  try {
    if (result === "failed") {
      const response = await ElMessageBox.prompt(
        "请简要说明乱码、缺页、尺寸或颜色等异常，方便后续排查。",
        "记录测试异常",
        { confirmButtonText: "保存记录", cancelButtonText: "取消", inputType: "textarea", inputValidator: (value) => Boolean(String(value || "").trim()) || "请输入异常说明" }
      );
      notes = String(response.value || "").trim();
    } else {
      await ElMessageBox.confirm(
        "请确认实体打印机已经实际出纸，并且文字、图形、分页均正常。",
        "确认实机验证",
        { type: "success", confirmButtonText: "确认正常", cancelButtonText: "取消" }
      );
    }
  } catch {
    return;
  }
  validationLoading.value = result;
  try {
    await api.post("/api/driver-validation", { model_id: modelId, result, notes });
    ElMessage.success(result === "passed" ? "已标记为实机验证通过" : "已记录实机测试异常");
    await searchCatalog(catalog.page);
    const refreshed = catalog.items.find((item) => item.model_id === modelId);
    if (refreshed) selectedCatalogModel.value = refreshed;
  } catch (error) {
    ElMessage.error(errorMessage(error, "保存实机验证结果失败"));
  } finally {
    validationLoading.value = "";
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

function recommendedLabel(row) {
  return row.catalog_recommendations?.[0]?.model || profileLabel(row.recommended_profile) || "请按设备型号选择";
}

function verificationLabel(row) {
  return { verified: "已实机验证", generic: "通用驱动", repository: "软件源支持", custom: "现场导入" }[row.verification] || "未验证";
}

function verificationType(row) {
  return row.verification === "verified" ? "success" : row.verification === "generic" ? "primary" : row.available ? "info" : "warning";
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
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

onMounted(async () => {
  await Promise.all([loadConfig(), searchCatalog(1)]);
});
onBeforeUnmount(() => window.clearTimeout(jobTimer));
</script>

<style scoped lang="scss">
.surface-heading > div { min-width: 0; }
.surface-heading .section-note { display: block; margin: 6px 0 0; line-height: 1.5; }
.catalog-toolbar {
  display: grid;
  grid-template-columns: minmax(300px, 1fr) 180px 160px auto;
  gap: 10px;
  margin: 14px 0;
}
.catalog-selection-alert { margin-bottom: 14px; }
.catalog-pagination { justify-content: flex-end; margin-top: 14px; }
.catalog-job-progress { margin-top: 18px; }
@media (max-width: 900px) {
  .catalog-toolbar { grid-template-columns: 1fr; }
  .catalog-pagination { justify-content: center; overflow-x: auto; }
}
</style>
