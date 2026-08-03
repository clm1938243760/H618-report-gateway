<script setup>
import { computed, reactive, ref, shallowRef } from "vue";
import { Download, Plus, Refresh, Upload } from "@element-plus/icons-vue";

const statusOptions = [
  { label: "全部", value: "" },
  { label: "进行中", value: "running" },
  { label: "待确认", value: "pending" },
  { label: "已完成", value: "done" },
  { label: "已暂停", value: "paused" }
];

const categoryOptions = [
  { label: "全部", value: "" },
  { label: "标准建设", value: "standard" },
  { label: "流程优化", value: "process" },
  { label: "数据治理", value: "data" }
];

const statusMeta = {
  running: { label: "进行中", type: "primary" },
  pending: { label: "待确认", type: "warning" },
  done: { label: "已完成", type: "success" },
  paused: { label: "已暂停", type: "info" }
};

const initialRows = [
  {
    id: "1876543210123456789",
    code: "JL-2026-001",
    name: "页面样式规范整理",
    category: "标准建设",
    department: "产品研发部",
    status: "running",
    priority: "高",
    progress: "70%",
    owner: "王建",
    planDate: "2026-05-12",
    budget: "12.80 万",
    updatedAt: "2026-05-06 10:20"
  },
  {
    id: "1876543210123456790",
    code: "JL-2026-002",
    name: "表格操作列规则同步",
    category: "流程优化",
    department: "交付管理部",
    status: "pending",
    priority: "中",
    progress: "45%",
    owner: "李思",
    planDate: "2026-05-15",
    budget: "8.50 万",
    updatedAt: "2026-05-05 16:48"
  },
  {
    id: "1876543210123456791",
    code: "JL-2026-003",
    name: "搜索表单字段梳理",
    category: "数据治理",
    department: "数据平台部",
    status: "done",
    priority: "中",
    progress: "100%",
    owner: "赵敏",
    planDate: "2026-05-08",
    budget: "6.20 万",
    updatedAt: "2026-05-04 14:36"
  },
  {
    id: "1876543210123456792",
    code: "JL-2026-004",
    name: "业务页面模板验收",
    category: "标准建设",
    department: "质量保障部",
    status: "paused",
    priority: "低",
    progress: "30%",
    owner: "陈林",
    planDate: "2026-05-18",
    budget: "4.60 万",
    updatedAt: "2026-05-03 09:12"
  },
  {
    id: "1876543210123456793",
    code: "JL-2026-005",
    name: "组件库样式发布确认",
    category: "流程优化",
    department: "前端平台部",
    status: "running",
    priority: "高",
    progress: "80%",
    owner: "周宁",
    planDate: "2026-05-10",
    budget: "10.00 万",
    updatedAt: "2026-05-02 18:05"
  },
  {
    id: "1876543210123456794",
    code: "JL-2026-006",
    name: "模板项目示例补齐",
    category: "标准建设",
    department: "业务支持部",
    status: "done",
    priority: "中",
    progress: "100%",
    owner: "孙悦",
    planDate: "2026-05-09",
    budget: "5.80 万",
    updatedAt: "2026-05-01 11:30"
  }
];

const rows = ref([...initialRows]);

const query = reactive({
  keyword: "",
  category: "",
  owner: "",
  updatedAt: "",
  status: ""
});

const pager = reactive({
  currentPage: 1,
  pageSize: 5
});

const selectedRows = shallowRef([]);
const formRef = ref();
const dialogVisible = ref(false);
const dialogMode = ref("create");
const editingRowId = ref("");
const deleteDialogVisible = ref(false);
const pendingDeleteRow = shallowRef(null);
const form = reactive({
  code: "",
  name: "",
  category: "",
  department: "",
  owner: "",
  priority: "",
  planDate: "",
  budget: "",
  progress: "",
  statusLabel: "",
  updatedAt: "",
  remark: ""
});

const formRules = {
  name: [{ required: true, message: "请输入事项名称", trigger: "blur" }],
  category: [{ required: true, message: "请选择类型", trigger: "change" }],
  department: [{ required: true, message: "请输入所属部门", trigger: "blur" }],
  owner: [{ required: true, message: "请输入负责人", trigger: "blur" }],
  priority: [{ required: true, message: "请选择优先级", trigger: "change" }],
  planDate: [{ required: true, message: "请选择完成时间", trigger: "change" }]
};

const filteredRows = computed(() => {
  const keyword = query.keyword.trim().toLowerCase();

  return rows.value.filter((row) => {
    const matchesKeyword = !keyword || row.name.toLowerCase().includes(keyword) || row.owner.toLowerCase().includes(keyword);
    const matchesCategory = !query.category || row.category === categoryOptions.find((item) => item.value === query.category)?.label;
    const matchesOwner = !query.owner || row.owner.includes(query.owner.trim());
    const matchesUpdatedAt = !query.updatedAt || row.updatedAt.startsWith(query.updatedAt);
    const matchesStatus = !query.status || row.status === query.status;

    return matchesKeyword && matchesCategory && matchesOwner && matchesUpdatedAt && matchesStatus;
  });
});

const pageRows = computed(() => {
  const start = (pager.currentPage - 1) * pager.pageSize;
  return filteredRows.value.slice(start, start + pager.pageSize);
});

const selectedCount = computed(() => selectedRows.value.length);
const dialogTitle = computed(() => {
  const titleMap = {
    create: "新增事项",
    detail: "事项详情",
    edit: "编辑事项"
  };

  return titleMap[dialogMode.value];
});
const isDialogReadonly = computed(() => dialogMode.value === "detail");
const detailItems = computed(() => [
  { label: "事项编号", value: form.code },
  { label: "事项名称", value: form.name },
  { label: "类型", value: form.category },
  { label: "所属部门", value: form.department },
  { label: "负责人", value: form.owner },
  { label: "优先级", value: form.priority },
  { label: "完成进度", value: form.progress },
  { label: "完成时间", value: form.planDate },
  { label: "预算金额", value: form.budget },
  { label: "状态", value: form.statusLabel },
  { label: "更新时间", value: form.updatedAt },
  { label: "备注", value: form.remark }
]);

function search() {
  pager.currentPage = 1;
}

function reset() {
  query.keyword = "";
  query.category = "";
  query.owner = "";
  query.updatedAt = "";
  query.status = "";
  pager.currentPage = 1;
}

function updateSelection(selection) {
  selectedRows.value = selection;
}

function getStatusMeta(status) {
  return statusMeta[status] || { label: status, type: "info" };
}

function resetForm() {
  Object.assign(form, {
    code: "",
    name: "",
    category: "",
    department: "",
    owner: "",
    priority: "",
    planDate: "",
    budget: "",
    progress: "",
    statusLabel: "",
    updatedAt: "",
    remark: ""
  });
}

function fillForm(row) {
  Object.assign(form, {
    code: row.code,
    name: row.name,
    category: row.category,
    department: row.department,
    owner: row.owner,
    priority: row.priority,
    planDate: row.planDate,
    budget: row.budget === "-" ? "" : row.budget.replace(/\s*万$/, ""),
    progress: row.progress,
    statusLabel: getStatusMeta(row.status).label,
    updatedAt: row.updatedAt,
    remark: "适用于事项字段较多、需要按详情信息稳定展示的弹窗详情页面。"
  });
}

function openCreateDialog() {
  dialogMode.value = "create";
  editingRowId.value = "";
  resetForm();
  dialogVisible.value = true;
}

function openDetailDialog(row) {
  dialogMode.value = "detail";
  editingRowId.value = row.id;
  fillForm(row);
  dialogVisible.value = true;
}

function openEditDialog(row) {
  dialogMode.value = "edit";
  editingRowId.value = row.id;
  fillForm(row);
  dialogVisible.value = true;
}

function openDeleteDialog(row) {
  pendingDeleteRow.value = row;
  deleteDialogVisible.value = true;
}

function closeDialog() {
  dialogVisible.value = false;
  formRef.value?.clearValidate();
}

function closeDeleteDialog() {
  deleteDialogVisible.value = false;
  pendingDeleteRow.value = null;
}

function confirmDelete() {
  const rowId = pendingDeleteRow.value?.id;
  if (!rowId) {
    closeDeleteDialog();
    return;
  }

  rows.value = rows.value.filter((row) => row.id !== rowId);
  selectedRows.value = selectedRows.value.filter((row) => row.id !== rowId);
  if (pageRows.value.length === 0 && pager.currentPage > 1) {
    pager.currentPage -= 1;
  }
  closeDeleteDialog();
}

async function submitForm() {
  await formRef.value?.validate();

  if (dialogMode.value === "edit") {
    const target = rows.value.find((row) => row.id === editingRowId.value);
    if (target) {
      Object.assign(target, {
        name: form.name,
        category: form.category,
        department: form.department,
        priority: form.priority,
        owner: form.owner,
        planDate: form.planDate,
        budget: form.budget ? `${form.budget} 万` : "-",
        updatedAt: new Date().toISOString().slice(0, 16).replace("T", " ")
      });
    }
    closeDialog();
    return;
  }

  const nextIndex = rows.value.length + 1;
  rows.value.unshift({
    id: String(Date.now()),
    code: `JL-2026-${String(nextIndex).padStart(3, "0")}`,
    name: form.name,
    category: form.category,
    department: form.department,
    status: "pending",
    priority: form.priority,
    progress: "0%",
    owner: form.owner,
    planDate: form.planDate,
    budget: form.budget ? `${form.budget} 万` : "-",
    updatedAt: new Date().toISOString().slice(0, 16).replace("T", " ")
  });
  pager.currentPage = 1;
  closeDialog();
}

function confirmDialog() {
  if (isDialogReadonly.value) {
    closeDialog();
    return;
  }

  submitForm();
}
</script>

<template>
  <section class="jl-page-shell standard-list-page">
    <div class="jl-search-card">
      <el-form class="jl-search-form" :model="query" label-width="auto">
        <el-row :gutter="24">
          <el-col :span="6">
            <el-form-item label="更新时间">
              <el-date-picker v-model="query.updatedAt" type="date" value-format="YYYY-MM-DD" placeholder="请选择"
                clearable />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="关键词">
              <el-input v-model="query.keyword" clearable placeholder="名称 / 负责人" @keyup.enter="search" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="类型">
              <el-select v-model="query.category" placeholder="请选择" clearable>
                <el-option v-for="item in categoryOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="负责人">
              <el-input v-model="query.owner" clearable placeholder="请输入负责人" @keyup.enter="search" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="状态">
              <el-select v-model="query.status" placeholder="请选择" clearable>
                <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label-width="0">
              <div class="jl-search-actions">
                <el-button type="primary" @click="search">查询</el-button>
                <el-button class="jl-button-auxiliary" @click="reset">重置</el-button>
              </div>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </div>

    <div class="jl-table-card">
      <div class="jl-table-toolbar">
        <div class="jl-table-toolbar__left">
          <el-button type="primary" :icon="Plus" @click="openCreateDialog">新增</el-button>
          <el-button class="jl-button-outline" :icon="Upload">导入</el-button>
          <el-button class="jl-button-outline" :icon="Download">导出</el-button>
          <el-button class="jl-button-outline" :icon="Refresh">刷新</el-button>
          <el-button class="jl-button-outline" :disabled="!selectedCount">批量处理</el-button>
        </div>
      </div>

      <el-table class="jl-standard-table" :data="pageRows" row-key="id" height="100%"
        @selection-change="updateSelection">
        <el-table-column type="selection" width="48" />
        <el-table-column prop="code" label="事项编号" width="140" />
        <el-table-column prop="name" label="事项名称" width="240" show-overflow-tooltip />
        <el-table-column prop="category" label="类型" width="130" />
        <el-table-column prop="department" label="所属部门" width="140" />
        <el-table-column prop="owner" label="负责人" width="120" />
        <el-table-column prop="priority" label="优先级" width="110" />
        <el-table-column prop="progress" label="完成进度" width="120" />
        <el-table-column prop="planDate" label="完成时间" width="150" />
        <el-table-column prop="budget" label="预算金额" width="120" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="getStatusMeta(row.status).type">{{ getStatusMeta(row.status).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="updatedAt" label="更新时间" width="170" />
        <el-table-column label="操作" fixed="right" width="160">
          <template #default="{ row }">
            <div class="jl-table-actions">
              <el-button link type="primary" @click="openDetailDialog(row)">详情</el-button>
              <el-button link type="primary" @click="openEditDialog(row)">编辑</el-button>
              <el-button link type="danger" @click="openDeleteDialog(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <span class="jl-empty-text">暂无数据</span>
        </template>
      </el-table>

      <div class="jl-pagination-wrap">
        <el-pagination v-model:current-page="pager.currentPage" v-model:page-size="pager.pageSize"
          :page-sizes="[5, 10, 20]" :total="filteredRows.length" background layout="total, prev, pager, next, sizes" />
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :width="isDialogReadonly ? '960px' : '640px'" :show-close="true" destroy-on-close @closed="closeDialog">
      <template #header>
        <JLDialogHeader :title="dialogTitle" type="info" />
      </template>

      <div v-if="isDialogReadonly" class="jl-detail-grid jl-detail-grid--label-136">
        <template v-for="item in detailItems" :key="item.label">
          <div class="jl-detail-grid__label">{{ item.label }}</div>
          <div class="jl-detail-grid__value">
            {{ item.value || "-" }}
          </div>
        </template>
      </div>

      <el-form v-else ref="formRef" :model="form" :rules="formRules" label-width="auto">
        <el-row :gutter="24">
          <el-col :span="12">
            <el-form-item label="事项名称" prop="name">
              <el-input v-model="form.name" placeholder="请输入事项名称" clearable />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="类型" prop="category">
              <el-select v-model="form.category" placeholder="请选择类型" clearable>
                <el-option v-for="item in categoryOptions.filter((option) => option.value)" :key="item.value"
                  :label="item.label" :value="item.label" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="所属部门" prop="department">
              <el-input v-model="form.department" placeholder="请输入所属部门" clearable />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="负责人" prop="owner">
              <el-input v-model="form.owner" placeholder="请输入负责人" clearable />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="优先级" prop="priority">
              <el-select v-model="form.priority" placeholder="请选择优先级" clearable>
                <el-option label="高" value="高" />
                <el-option label="中" value="中" />
                <el-option label="低" value="低" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="完成时间" prop="planDate">
              <el-date-picker v-model="form.planDate" type="date" value-format="YYYY-MM-DD" placeholder="请选择"
                clearable />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="预算金额" prop="budget">
              <el-input v-model="form.budget" placeholder="请输入预算金额">
                <template #append>万</template>
              </el-input>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>

      <template #footer>
        <div class="standard-list-dialog-footer">
          <el-button class="jl-button-auxiliary" @click="closeDialog">取消</el-button>
          <el-button type="primary" @click="confirmDialog">确认</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="deleteDialogVisible" width="480px" :show-close="true" title="删除确认" @closed="closeDeleteDialog">
      <template #header>
        <JLDialogHeader title="删除确认" type="warning" />
      </template>

      <p>确认删除“{{ pendingDeleteRow?.name || "-" }}”吗？删除后将无法恢复。</p>

      <template #footer>
        <el-button class="jl-button-auxiliary" @click="closeDeleteDialog">取消</el-button>
        <el-button type="primary" @click="confirmDelete">确认</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.standard-list-page {
  min-width: 960px;
}

.standard-list-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
