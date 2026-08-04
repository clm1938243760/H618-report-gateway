<template>
  <div class="page-shell" v-loading="loading">
    <div class="page-heading">
      <h1>配置管理</h1>
      <div class="page-actions">
        <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
        <el-button :icon="Upload" :loading="testing" @click="testUpload">测试上传</el-button>
        <el-button type="primary" :icon="DocumentChecked" :loading="saving" @click="saveConfig">
          保存配置并生成 XML
        </el-button>
      </div>
    </div>

    <div class="status-grid">
      <div class="status-card">
        <span class="status-label">工作模式</span>
        <strong class="status-value">{{ modeName }}</strong>
      </div>
      <div class="status-card">
        <span class="status-label">USB 连接状态</span>
        <strong class="status-value" :class="udcClass">{{ udcName }}</strong>
      </div>
      <div class="status-card">
        <span class="status-label">XML 状态</span>
        <strong class="status-value" :class="status.xml_valid ? 'success' : 'warning'">
          {{ status.xml_valid ? "有效" : "无效" }}
        </strong>
      </div>
      <div class="status-card">
        <span class="status-label">待处理报告</span>
        <strong class="status-value">{{ pendingReports }}</strong>
      </div>
      <div class="status-card">
        <span class="status-label">剩余空间</span>
        <strong class="status-value">{{ formatBytes(status.disk_free) }}</strong>
      </div>
    </div>

    <section class="surface mode-row">
      <div class="mode-copy">
        <h2>USB 工作模式</h2>
        <p>{{ modeDescription }}</p>
      </div>
      <el-button-group class="mode-switch">
        <el-button
          :type="form.mode === 'msc_hid' ? 'primary' : 'default'"
          :loading="switching && requestedMode === 'msc_hid'"
          @click="changeMode('msc_hid')"
        >
          U盘 + HID
        </el-button>
        <el-button
          :type="form.mode === 'printer_hid' ? 'primary' : 'default'"
          :loading="switching && requestedMode === 'printer_hid'"
          @click="changeMode('printer_hid')"
        >
          打印 + HID
        </el-button>
        <el-button
          :type="form.mode === 'msc' ? 'primary' : 'default'"
          :loading="switching && requestedMode === 'msc'"
          @click="changeMode('msc')"
        >
          仅U盘
        </el-button>
        <el-button
          :type="form.mode === 'printer' ? 'primary' : 'default'"
          :loading="switching && requestedMode === 'printer'"
          @click="changeMode('printer')"
        >
          仅打印
        </el-button>
      </el-button-group>
    </section>

    <el-form ref="formRef" :model="form" label-position="top">
      <section class="surface">
        <div class="surface-heading">
          <h2>ReportInfo.xml</h2>
          <el-tag :type="status.xml_valid ? 'success' : 'danger'" effect="light">
            {{ status.xml_valid ? "XML 有效" : "XML 无效" }}
          </el-tag>
        </div>
        <div class="form-grid">
          <el-form-item
            label="设备编码"
            prop="device_code"
            :rules="[{ required: true, message: '请输入设备编码', trigger: 'blur' }]"
          >
            <el-input v-model="form.device_code" maxlength="128" />
          </el-form-item>
          <el-form-item
            label="检查医生"
            prop="exam_doct"
            :rules="[{ required: true, message: '请输入检查医生', trigger: 'blur' }]"
          >
            <el-input v-model="form.exam_doct" maxlength="128" />
          </el-form-item>
          <el-form-item
            label="检查医生编码"
            prop="exam_doct_code"
            :rules="[{ required: true, message: '请输入检查医生编码', trigger: 'blur' }]"
          >
            <el-input v-model="form.exam_doct_code" maxlength="128" />
          </el-form-item>
        </div>
        <p v-if="status.xml_error" class="section-note">{{ status.xml_error }}</p>
      </section>

      <section class="surface">
        <div class="surface-heading">
          <h2>上传配置</h2>
        </div>
        <div class="form-grid five-columns">
          <el-form-item label="上传状态">
            <el-select v-model="form.upload_enabled">
              <el-option label="启用" :value="true" />
              <el-option label="停用" :value="false" />
            </el-select>
          </el-form-item>
          <el-form-item label="重复文件去重">
            <el-switch
              v-model="form.deduplicate"
              inline-prompt
              active-text="开"
              inactive-text="关"
            />
          </el-form-item>
          <el-form-item
            label="上传服务（IP:端口）"
            prop="endpoint_host"
            :rules="[{ validator: validateEndpoint, trigger: 'blur' }]"
          >
            <el-input v-model="form.endpoint_host" placeholder="192.168.112.139:9061" />
          </el-form-item>
          <el-form-item label="超时（秒）">
            <el-input-number v-model="form.timeout_seconds" :min="1" :max="300" controls-position="right" />
          </el-form-item>
          <el-form-item label="重试间隔（秒）">
            <el-input-number
              v-model="form.retry_interval_seconds"
              :min="1"
              :max="86400"
              controls-position="right"
            />
          </el-form-item>
          <el-form-item label="最大尝试次数">
            <el-input-number v-model="form.max_attempts" :min="1" :max="20" controls-position="right" />
          </el-form-item>
        </div>
        <p class="section-note">
          实际上传地址：{{ endpointPreview || "请填写有效的 IP:端口" }}
        </p>
        <p class="section-note">
          {{
            form.deduplicate
              ? "去重已开启：内容相同的报告只提取并上传一次，适合正式运行。"
              : "去重已关闭：允许同一文件重复提取和上传，适合现场测试；SHA-256 完整性校验仍然启用。"
          }}
        </p>
      </section>
    </el-form>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { DocumentChecked, Refresh, Upload } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, errorMessage } from "@/api/client";
import { buildUploadEndpoint, endpointToHost } from "@/utils/endpoint";
import { formatBytes } from "@/utils/format";

const formRef = ref();
const loading = ref(false);
const saving = ref(false);
const testing = ref(false);
const switching = ref(false);
const requestedMode = ref("");
const status = reactive({
  mode: "msc",
  udc_state: "missing",
  xml_valid: false,
  xml_error: "",
  report_counts: {},
  disk_free: 0,
  disk_total: 0
});
const form = reactive({
  mode: "msc",
  device_code: "",
  exam_doct: "",
  exam_doct_code: "",
  upload_enabled: true,
  deduplicate: true,
  endpoint_host: "",
  timeout_seconds: 30,
  retry_interval_seconds: 60,
  max_attempts: 3,
  cleanup_enabled: true,
  cleanup_interval_hours: 24,
  report_retention_days: 30,
  log_retention_days: 14
});

const modeOptions = {
  msc_hid: {
    label: "U盘上传 + HID",
    description: "从模拟 U 盘提取报告，同时提供 HID 键盘和鼠标。"
  },
  printer_hid: {
    label: "打印上传 + HID",
    description: "接收 USB 打印任务，同时提供 HID 键盘和鼠标。"
  },
  msc: {
    label: "仅U盘上传",
    description: "从模拟 U 盘提取报告，转换后自动上传。"
  },
  printer: {
    label: "仅打印上传",
    description: "接收 USB 打印任务，转换为 PDF 后自动上传。"
  }
};
const modeName = computed(() => modeOptions[form.mode]?.label || form.mode);
const modeDescription = computed(() => modeOptions[form.mode]?.description || "");
const endpointPreview = computed(() => {
  try {
    return buildUploadEndpoint(form.endpoint_host);
  } catch {
    return "";
  }
});
const pendingReports = computed(() => {
  const counts = status.report_counts || {};
  return Number(counts.pending || 0) + Number(counts.uploading || 0) + Number(counts.retry_wait || 0);
});
const udcName = computed(() => {
  const mapping = {
    configured: "已连接",
    "not attached": "未连接",
    attached: "连接中",
    powered: "连接中",
    default: "连接中",
    addressed: "连接中",
    suspended: "已挂起",
    missing: "控制器不可用"
  };
  return mapping[status.udc_state] || "连接中";
});
const udcClass = computed(() =>
  status.udc_state === "configured"
    ? "success"
    : ["missing", "not attached"].includes(status.udc_state)
      ? "warning"
      : ""
);

function validateEndpoint(rule, value, callback) {
  try {
    buildUploadEndpoint(value);
    callback();
  } catch (error) {
    callback(error);
  }
}

async function loadAll() {
  loading.value = true;
  try {
    const [statusResponse, configResponse] = await Promise.all([
      api.get("/api/status"),
      api.get("/api/config")
    ]);
    Object.assign(status, statusResponse.data);
    const config = configResponse.data;
    Object.assign(form, config, {
      endpoint_host: endpointToHost(config.endpoint),
      mode: config.mode
    });
  } catch (error) {
    ElMessage.error(errorMessage(error, "加载配置失败"));
  } finally {
    loading.value = false;
  }
}

async function saveConfig() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid || saving.value) return;
  saving.value = true;
  try {
    const endpoint = buildUploadEndpoint(form.endpoint_host);
    const { data } = await api.put("/api/config", {
      device_code: form.device_code,
      exam_doct: form.exam_doct,
      exam_doct_code: form.exam_doct_code,
      upload_enabled: form.upload_enabled,
      deduplicate: form.deduplicate,
      endpoint,
      timeout_seconds: form.timeout_seconds,
      retry_interval_seconds: form.retry_interval_seconds,
      max_attempts: form.max_attempts,
      cleanup_enabled: form.cleanup_enabled,
      cleanup_interval_hours: form.cleanup_interval_hours,
      report_retention_days: form.report_retention_days,
      log_retention_days: form.log_retention_days
    });
    if (data.warning) {
      ElMessage.warning("配置已保存，但采集服务重启失败，请检查服务状态");
    } else {
      ElMessage.success("配置已保存，ReportInfo.xml 已重新生成");
    }
    await loadAll();
  } catch (error) {
    ElMessage.error(errorMessage(error, "保存配置失败"));
  } finally {
    saving.value = false;
  }
}

async function changeMode(mode) {
  if (mode === form.mode || switching.value) return;
  const label = modeOptions[mode]?.label || mode;
  try {
    await ElMessageBox.confirm(
      `切换到“${label}”会短暂重建 USB 复合设备，是否继续？`,
      "切换工作模式",
      { type: "warning", confirmButtonText: "确认切换", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  switching.value = true;
  requestedMode.value = mode;
  try {
    await api.post("/api/gadget/switch", { mode });
    form.mode = mode;
    status.mode = mode;
    ElMessage.success(`已切换为${label}`);
    await loadAll();
  } catch (error) {
    ElMessage.error(errorMessage(error, "模式切换失败"));
  } finally {
    switching.value = false;
    requestedMode.value = "";
  }
}

async function testUpload() {
  testing.value = true;
  try {
    const { data } = await api.post("/api/upload/test");
    if (data.ok) {
      ElMessage.success(`测试完成，已处理 ${data.processed} 份报告`);
    } else {
      ElMessage.warning("当前没有可测试上传的待处理报告");
    }
    await loadAll();
  } catch (error) {
    ElMessage.error(errorMessage(error, "测试上传失败"));
  } finally {
    testing.value = false;
  }
}

onMounted(loadAll);
</script>
