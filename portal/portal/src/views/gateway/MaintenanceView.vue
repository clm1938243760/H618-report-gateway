<template>
  <div class="page-shell" v-loading="loading">
    <div class="page-heading">
      <h1>存储与清理</h1>
      <div class="page-actions">
        <el-button :icon="Refresh" @click="loadData">刷新</el-button>
        <el-button type="primary" :icon="DocumentChecked" :loading="saving" @click="save">
          保存清理策略
        </el-button>
      </div>
    </div>

    <section class="surface">
      <div class="surface-heading">
        <h2>自动清理策略</h2>
        <el-tag :type="form.cleanup_enabled ? 'success' : 'info'">
          {{ form.cleanup_enabled ? "已启用" : "已停用" }}
        </el-tag>
      </div>
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="自动清理">
            <el-select v-model="form.cleanup_enabled">
              <el-option label="启用" :value="true" />
              <el-option label="停用" :value="false" />
            </el-select>
          </el-form-item>
          <el-form-item label="执行间隔（小时）">
            <el-input-number v-model="form.cleanup_interval_hours" :min="1" :max="720" controls-position="right" />
          </el-form-item>
          <div></div>
          <el-form-item label="已上传报告保留天数">
            <el-input-number v-model="form.report_retention_days" :min="1" :max="3650" controls-position="right" />
          </el-form-item>
          <el-form-item label="运行日志保留天数">
            <el-input-number v-model="form.log_retention_days" :min="1" :max="3650" controls-position="right" />
          </el-form-item>
        </div>
      </el-form>
      <p class="section-note">
        执行间隔表示后台每隔多少小时检查一次过期文件；只删除已上传成功且超过保留天数的报告。
      </p>
    </section>

    <section class="surface">
      <div class="surface-heading">
        <h2>运行信息</h2>
      </div>
      <div class="maintenance-summary">
        <div class="summary-item">
          <span>当前状态</span>
          <strong>{{ maintenance.running ? "正在清理" : "等待执行" }}</strong>
        </div>
        <div class="summary-item">
          <span>上次执行时间</span>
          <strong>{{ formatTime(maintenance.last_run_at) }}</strong>
        </div>
        <div class="summary-item">
          <span>下次执行时间</span>
          <strong>{{ form.cleanup_enabled ? formatTime(maintenance.next_run_at) : "未启用" }}</strong>
        </div>
      </div>
      <el-collapse v-if="hasLastResult" style="margin-top: 16px">
        <el-collapse-item title="查看上次清理结果">
          <pre class="detail-block">{{ JSON.stringify(maintenance.last_result, null, 2) }}</pre>
        </el-collapse-item>
      </el-collapse>
    </section>

    <section class="surface">
      <div class="surface-heading">
        <h2>手动清理</h2>
      </div>
      <p class="section-note">手动清理立即按照当前保留天数执行，不改变自动清理策略。</p>
      <div class="danger-actions">
        <el-button :loading="cleaning === 'reports'" @click="cleanup('reports')">清理过期报告</el-button>
        <el-button :loading="cleaning === 'logs'" @click="cleanup('logs')">清理过期日志</el-button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { DocumentChecked, Refresh } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, errorMessage } from "@/api/client";
import { formatTime } from "@/utils/format";

const loading = ref(false);
const saving = ref(false);
const cleaning = ref("");
const sourceConfig = ref({});
const form = reactive({
  cleanup_enabled: true,
  cleanup_interval_hours: 24,
  report_retention_days: 30,
  log_retention_days: 14
});
const maintenance = reactive({
  running: false,
  last_run_at: 0,
  next_run_at: 0,
  last_result: {}
});
const hasLastResult = computed(() => Object.keys(maintenance.last_result || {}).length > 0);

async function loadData() {
  loading.value = true;
  try {
    const [configResponse, statusResponse] = await Promise.all([
      api.get("/api/config"),
      api.get("/api/maintenance")
    ]);
    sourceConfig.value = configResponse.data;
    Object.assign(form, {
      cleanup_enabled: configResponse.data.cleanup_enabled,
      cleanup_interval_hours: configResponse.data.cleanup_interval_hours,
      report_retention_days: configResponse.data.report_retention_days,
      log_retention_days: configResponse.data.log_retention_days
    });
    Object.assign(maintenance, statusResponse.data);
  } catch (error) {
    ElMessage.error(errorMessage(error, "加载清理配置失败"));
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  try {
    await api.put("/api/config", {
      ...sourceConfig.value,
      ...form
    });
    ElMessage.success("清理策略已保存");
    await loadData();
  } catch (error) {
    ElMessage.error(errorMessage(error, "保存清理策略失败"));
  } finally {
    saving.value = false;
  }
}

async function cleanup(kind) {
  const label = kind === "reports" ? "过期报告" : "过期日志";
  try {
    await ElMessageBox.confirm(`确认立即清理${label}吗？`, "手动清理", {
      type: "warning",
      confirmButtonText: "立即清理",
      cancelButtonText: "取消"
    });
  } catch {
    return;
  }
  cleaning.value = kind;
  try {
    const { data } = await api.post("/api/maintenance/cleanup", { kind });
    ElMessage.success(`${label}清理完成`);
    maintenance.last_result = data.result || {};
    await loadData();
  } catch (error) {
    ElMessage.error(errorMessage(error, "手动清理失败"));
  } finally {
    cleaning.value = "";
  }
}

onMounted(loadData);
</script>
