<template>
  <div class="page-shell">
    <div class="page-heading">
      <h1>报告日志</h1>
      <div class="page-actions">
        <el-button type="primary" :icon="Refresh" :loading="loading" @click="loadReports">
          刷新
        </el-button>
      </div>
    </div>

    <section class="surface">
      <div class="filter-row">
        <label class="filter-field">
          <span>时间范围</span>
          <el-date-picker
            v-model="filters.range"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            value-format="X"
            style="width: 390px"
          />
        </label>
        <label class="filter-field status">
          <span>上传状态</span>
          <el-select v-model="filters.status">
            <el-option label="全部状态" value="" />
            <el-option label="待上传" value="pending" />
            <el-option label="上传成功" value="success" />
            <el-option label="上传失败" value="failed" />
          </el-select>
        </label>
        <el-button type="primary" :icon="Search" @click="applyFilters">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>
    </section>

    <section class="surface reports-table">
      <el-table v-loading="loading" :data="jobs" stripe height="560" class="desktop-only">
        <el-table-column label="采集时间" width="178">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="报告文件" min-width="230" show-overflow-tooltip>
          <template #default="{ row }">
            <strong>{{ row.pdf_name }}</strong>
            <div class="status-label">{{ formatBytes(row.pdf_size) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="120">
          <template #default="{ row }">{{ sourceName(row.source) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="125">
          <template #default="{ row }">
            <el-tag :type="statusMeta(row.status).type" effect="light">
              {{ statusMeta(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="attempts" label="尝试次数" width="100" align="center" />
        <el-table-column prop="last_http_status" label="HTTP 状态" width="110" align="center">
          <template #default="{ row }">{{ row.last_http_status || "-" }}</template>
        </el-table-column>
        <el-table-column label="错误信息" min-width="210">
          <template #default="{ row }">
            <div class="error-summary">{{ shortError(row) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="270" fixed="right">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button link type="primary" :icon="Download" @click="downloadReport(row)">
                下载
              </el-button>
              <el-button v-if="row.last_error || row.last_response" link type="primary" @click="showDetail(row)">
                查看详情
              </el-button>
              <el-button
                v-if="['retry_wait', 'exhausted'].includes(row.status)"
                link
                type="primary"
                @click="retry(row)"
              >
                失败重试
              </el-button>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无报告记录" :image-size="92" />
        </template>
      </el-table>
      <div v-loading="loading" class="mobile-only mobile-record-list">
        <article v-for="row in jobs" :key="row.id" class="mobile-record">
          <div class="mobile-record-heading">
            <div>
              <strong>{{ row.pdf_name }}</strong>
              <span>{{ formatTime(row.created_at) }} · {{ formatBytes(row.pdf_size) }}</span>
            </div>
            <el-tag :type="statusMeta(row.status).type" effect="light">
              {{ statusMeta(row.status).label }}
            </el-tag>
          </div>
          <dl class="mobile-record-meta">
            <dt>来源</dt>
            <dd>{{ sourceName(row.source) }}</dd>
            <dt>尝试次数</dt>
            <dd>{{ row.attempts }}</dd>
            <dt>HTTP 状态</dt>
            <dd>{{ row.last_http_status || "-" }}</dd>
            <dt>结果</dt>
            <dd :class="{ 'error-text': row.last_error }">{{ shortError(row) }}</dd>
          </dl>
          <div class="mobile-record-actions">
            <el-button type="primary" plain :icon="Download" @click="downloadReport(row)">下载</el-button>
            <el-button v-if="row.last_error || row.last_response" @click="showDetail(row)">查看详情</el-button>
            <el-button
              v-if="['retry_wait', 'exhausted'].includes(row.status)"
              @click="retry(row)"
            >
              失败重试
            </el-button>
          </div>
        </article>
        <el-empty v-if="!loading && jobs.length === 0" description="暂无报告记录" :image-size="76" />
      </div>
      <div class="pagination-row">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @change="loadReports"
        />
      </div>
    </section>

    <el-dialog v-model="detailVisible" title="上传失败详情" width="760px">
      <dl v-if="selected" class="detail-list">
        <dt>报告文件</dt>
        <dd>{{ selected.pdf_name }}</dd>
        <dt>HTTP 状态</dt>
        <dd>{{ selected.last_http_status || "-" }}</dd>
        <dt>尝试次数</dt>
        <dd>{{ selected.attempts }}</dd>
        <dt>错误信息</dt>
        <dd class="detail-block">{{ selected.last_error || "-" }}</dd>
        <dt>接口响应</dt>
        <dd class="detail-block">{{ selected.last_response || "-" }}</dd>
      </dl>
      <template #footer>
        <el-button type="primary" @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { Download, Refresh, Search } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, errorMessage } from "@/api/client";
import { formatBytes, formatTime } from "@/utils/format";

const loading = ref(false);
const jobs = ref([]);
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const detailVisible = ref(false);
const selected = ref(null);
const filters = reactive({ range: [], status: "" });

function statusMeta(status) {
  const mapping = {
    pending: { label: "待上传", type: "info" },
    uploading: { label: "上传中", type: "warning" },
    retry_wait: { label: "等待重试", type: "warning" },
    exhausted: { label: "上传失败", type: "danger" },
    uploaded: { label: "上传成功", type: "success" }
  };
  return mapping[status] || { label: status || "未知", type: "info" };
}

function sourceName(source) {
  return source === "printer" ? "打印上传" : source === "msc" ? "U盘上传" : source || "-";
}

function shortError(row) {
  if (!row.last_error) return "-";
  return row.status === "retry_wait" ? "上传失败，等待重试" : "上传失败";
}

async function loadReports() {
  loading.value = true;
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      status: filters.status
    };
    if (filters.range?.length === 2) {
      params.start = Number(filters.range[0]);
      params.end = Number(filters.range[1]);
    }
    const { data } = await api.get("/api/reports", { params });
    jobs.value = data.jobs || [];
    page.value = data.page || 1;
    pageSize.value = data.page_size || pageSize.value;
    total.value = data.total || 0;
  } catch (error) {
    ElMessage.error(errorMessage(error, "加载报告日志失败"));
  } finally {
    loading.value = false;
  }
}

function applyFilters() {
  page.value = 1;
  loadReports();
}

function resetFilters() {
  filters.range = [];
  filters.status = "";
  applyFilters();
}

function showDetail(row) {
  selected.value = row;
  detailVisible.value = true;
}

function downloadReport(row) {
  const link = document.createElement("a");
  link.href = `/api/reports/${row.id}/download`;
  link.download = row.pdf_name;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function retry(row) {
  try {
    await ElMessageBox.confirm(`确认重新上传“${row.pdf_name}”吗？`, "失败重试", {
      type: "warning",
      confirmButtonText: "重新上传",
      cancelButtonText: "取消"
    });
  } catch {
    return;
  }
  try {
    const { data } = await api.post(`/api/reports/${row.id}/retry`);
    if (!data.ok) throw new Error("该记录当前不能重试");
    ElMessage.success("已重新加入上传队列");
    await loadReports();
  } catch (error) {
    ElMessage.error(errorMessage(error, "重试失败"));
  }
}

onMounted(loadReports);
</script>
