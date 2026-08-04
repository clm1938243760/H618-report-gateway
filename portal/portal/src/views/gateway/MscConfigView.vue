<template>
  <div class="page-shell" v-loading="loading">
    <div class="page-heading">
      <h1>模拟U盘配置</h1>
      <div class="page-actions">
        <el-button :icon="Refresh" @click="loadConfig">刷新</el-button>
        <el-button type="danger" plain :icon="RefreshRight" :loading="rebuilding" @click="rebuildImage">
          重建U盘
        </el-button>
        <el-button type="primary" :icon="DocumentChecked" :loading="saving" @click="saveConfig">
          保存配置
        </el-button>
      </div>
    </div>

    <div class="configuration-summary">
      <div class="summary-item">
        <span>当前镜像容量</span>
        <strong>{{ formatBytes(form.actual_size_bytes) }}</strong>
      </div>
      <div class="summary-item">
        <span>配置容量</span>
        <strong>{{ form.image_size_mb }} MB</strong>
      </div>
      <div class="summary-item">
        <span>运行状态</span>
        <strong :class="form.active ? 'success-text' : ''">{{ form.active ? "U盘模式运行中" : "当前未启用" }}</strong>
      </div>
      <div class="summary-item">
        <span>受保护文件</span>
        <strong>{{ protectedCount }} 个</strong>
      </div>
    </div>

    <el-alert
      v-if="form.rebuild_required"
      title="配置容量与当前镜像不一致，需要点击“重建U盘”后才能生效。"
      type="warning"
      :closable="false"
      show-icon
      class="page-alert"
    />

    <el-form ref="formRef" :model="form" label-position="top">
      <section class="surface">
        <div class="surface-heading"><h2>镜像与采集</h2></div>
        <div class="form-grid">
          <el-form-item label="U盘容量（MB）">
            <el-input-number v-model="form.image_size_mb" :min="32" :max="4096" :step="32" controls-position="right" />
          </el-form-item>
          <el-form-item label="卷标" prop="label" :rules="labelRules">
            <el-input v-model="form.label" maxlength="11" placeholder="USB DISK" />
          </el-form-item>
          <el-form-item label="重复文件去重">
            <el-switch v-model="form.deduplicate" inline-prompt active-text="开" inactive-text="关" />
          </el-form-item>
          <el-form-item label="读取后自动删除">
            <el-switch v-model="form.auto_delete" inline-prompt active-text="开" inactive-text="关" />
          </el-form-item>
          <el-form-item label="缺失时恢复标志文件">
            <el-switch v-model="form.restore_protected_files" inline-prompt active-text="开" inactive-text="关" />
          </el-form-item>
        </div>
        <p class="section-note">
          自动删除仅在复制校验和 PDF 转换成功后执行；受保护文件不会作为报告读取或删除。
        </p>
      </section>

      <section class="surface">
        <div class="surface-heading"><h2>标志文件保护</h2></div>
        <el-form-item label="U盘内相对路径（每行一个）">
          <el-input
            v-model="protectedText"
            type="textarea"
            :rows="6"
            resize="none"
            placeholder="例如：DEVICE.INI&#10;Config/marker.dat"
          />
        </el-form-item>
        <div v-if="form.protected_status.length" class="protected-status-list">
          <span v-for="item in form.protected_status" :key="item.path">
            <el-icon :class="item.seeded ? 'success-text' : 'warning-text'">
              <CircleCheck v-if="item.seeded" /><Warning v-else />
            </el-icon>
            {{ item.path }}：{{ item.seeded ? "已有恢复副本" : "等待首次发现" }}
          </span>
        </div>
      </section>
    </el-form>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { CircleCheck, DocumentChecked, Refresh, RefreshRight, Warning } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, errorMessage } from "@/api/client";
import { formatBytes } from "@/utils/format";

const formRef = ref();
const loading = ref(false);
const saving = ref(false);
const rebuilding = ref(false);
const protectedText = ref("");
const form = reactive({
  image_size_mb: 512,
  actual_size_bytes: 0,
  label: "USB DISK",
  auto_delete: false,
  deduplicate: true,
  restore_protected_files: true,
  protected_files: [],
  protected_status: [],
  rebuild_required: false,
  active: false
});
const protectedCount = computed(() => protectedLines().length);
const labelRules = [
  { required: true, message: "请输入U盘卷标", trigger: "blur" },
  { pattern: /^[\x20-\x7e]{1,11}$/, message: "卷标只能使用最多 11 个 ASCII 字符", trigger: "blur" }
];

function protectedLines() {
  return protectedText.value
    .split(/\r?\n/)
    .map((value) => value.trim().replaceAll("\\", "/"))
    .filter((value, index, values) => value && values.indexOf(value) === index);
}

async function loadConfig() {
  loading.value = true;
  try {
    const { data } = await api.get("/api/msc/config");
    Object.assign(form, data);
    protectedText.value = (data.protected_files || []).join("\n");
  } catch (error) {
    ElMessage.error(errorMessage(error, "加载模拟U盘配置失败"));
  } finally {
    loading.value = false;
  }
}

async function saveConfig() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid || saving.value) return;
  saving.value = true;
  try {
    const { data } = await api.put("/api/msc/config", {
      image_size_mb: form.image_size_mb,
      label: form.label,
      auto_delete: form.auto_delete,
      deduplicate: form.deduplicate,
      restore_protected_files: form.restore_protected_files,
      protected_files: protectedLines()
    });
    ElMessage.success(data.rebuild_required ? "配置已保存，容量变更需要重建U盘" : "模拟U盘配置已保存");
    await loadConfig();
  } catch (error) {
    ElMessage.error(errorMessage(error, "保存模拟U盘配置失败"));
  } finally {
    saving.value = false;
  }
}

async function rebuildImage() {
  try {
    await ElMessageBox.confirm(
      `将格式化并重建 ${form.image_size_mb} MB 模拟U盘，未采集文件会被清空。`,
      "重建模拟U盘",
      { type: "error", confirmButtonText: "确认格式化重建", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  rebuilding.value = true;
  try {
    await api.post("/api/msc/rebuild", { confirm: true });
    ElMessage.success("模拟U盘已重建");
    await loadConfig();
  } catch (error) {
    ElMessage.error(errorMessage(error, "重建模拟U盘失败"));
  } finally {
    rebuilding.value = false;
  }
}

onMounted(loadConfig);
</script>
