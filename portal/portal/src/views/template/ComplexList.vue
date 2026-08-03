<script setup>
import { computed, reactive, ref, shallowRef } from "vue";
import { useRouter } from "vue-router";

const router = useRouter();

const statusOptions = [
  { label: "全部", value: "" },
  { label: "拟定中", value: "draft" },
  { label: "审批中", value: "approval" },
  { label: "执行中", value: "running" },
  { label: "已完成", value: "done" }
];

const typeOptions = [
  { label: "全部", value: "" },
  { label: "技术开发", value: "development" },
  { label: "专利权转让", value: "patent" },
  { label: "技术服务", value: "service" }
];

const statusMeta = {
  draft: { label: "拟定中", type: "info" },
  approval: { label: "审批中", type: "warning" },
  running: { label: "执行中", type: "primary" },
  done: { label: "已完成", type: "success" }
};

const rows = ref([
  {
    id: "2049736613293502465",
    code: "TJ-CGB-2026-0002",
    name: "测试合同",
    type: "专利权转让",
    projectName: "智慧病区数据治理项目",
    partner: "甲方：1111；乙方：123",
    amount: "100,000.00",
    paidAmount: "100,000.00",
    remainingAmount: "0.00",
    owner: "王建",
    status: "running",
    signedAt: "2026-04-30",
    updatedAt: "2026-05-07 15:20"
  },
  {
    id: "2049736613293502466",
    code: "TJ-CGB-2026-0003",
    name: "科研成果转化服务合同",
    type: "技术服务",
    projectName: "院内科研服务协同平台",
    partner: "甲方：津莱医院；乙方：华北技术服务中心",
    amount: "86,500.00",
    paidAmount: "20,000.00",
    remainingAmount: "66,500.00",
    owner: "李思",
    status: "approval",
    signedAt: "2026-05-02",
    updatedAt: "2026-05-06 09:48"
  },
  {
    id: "2049736613293502467",
    code: "TJ-CGB-2026-0004",
    name: "技术开发委托合同",
    type: "技术开发",
    projectName: "临床数据质控模型",
    partner: "甲方：津莱医院；乙方：数智研发部",
    amount: "238,000.00",
    paidAmount: "80,000.00",
    remainingAmount: "158,000.00",
    owner: "赵敏",
    status: "draft",
    signedAt: "2026-05-04",
    updatedAt: "2026-05-05 18:12"
  },
  {
    id: "2049736613293502468",
    code: "TJ-CGB-2026-0005",
    name: "专利许可合同",
    type: "专利权转让",
    projectName: "影像辅助诊断专利许可",
    partner: "甲方：津莱医院；乙方：启明医疗科技",
    amount: "160,000.00",
    paidAmount: "160,000.00",
    remainingAmount: "0.00",
    owner: "陈林",
    status: "done",
    signedAt: "2026-04-26",
    updatedAt: "2026-05-03 11:36"
  },
  {
    id: "2049736613293502469",
    code: "TJ-CGB-2026-0006",
    name: "成果转化联合开发合同",
    type: "技术开发",
    projectName: "智能护理巡检终端",
    partner: "甲方：津莱医院；乙方：南方联合实验室",
    amount: "320,000.00",
    paidAmount: "120,000.00",
    remainingAmount: "200,000.00",
    owner: "周宁",
    status: "running",
    signedAt: "2026-04-18",
    updatedAt: "2026-05-02 16:05"
  },
  {
    id: "2049736613293502470",
    code: "TJ-CGB-2026-0007",
    name: "知识产权运营合同",
    type: "技术服务",
    projectName: "知识产权运营体系建设",
    partner: "甲方：津莱医院；乙方：知识产权运营中心",
    amount: "58,000.00",
    paidAmount: "0.00",
    remainingAmount: "58,000.00",
    owner: "孙悦",
    status: "approval",
    signedAt: "2026-04-12",
    updatedAt: "2026-05-01 10:30"
  }
]);

const query = reactive({
  keyword: "",
  type: "",
  owner: "",
  signedAt: "",
  status: ""
});

const pager = reactive({
  currentPage: 1,
  pageSize: 5
});

const selectedRows = shallowRef([]);

const filteredRows = computed(() => {
  const keyword = query.keyword.trim().toLowerCase();

  return rows.value.filter((row) => {
    const matchesKeyword =
      !keyword ||
      row.name.toLowerCase().includes(keyword) ||
      row.code.toLowerCase().includes(keyword) ||
      row.projectName.toLowerCase().includes(keyword);
    const matchesType = !query.type || row.type === typeOptions.find((item) => item.value === query.type)?.label;
    const matchesOwner = !query.owner || row.owner.includes(query.owner.trim());
    const matchesSignedAt = !query.signedAt || row.signedAt === query.signedAt;
    const matchesStatus = !query.status || row.status === query.status;

    return matchesKeyword && matchesType && matchesOwner && matchesSignedAt && matchesStatus;
  });
});

const pageRows = computed(() => {
  const start = (pager.currentPage - 1) * pager.pageSize;
  return filteredRows.value.slice(start, start + pager.pageSize);
});

const selectedCount = computed(() => selectedRows.value.length);

function search() {
  pager.currentPage = 1;
}

function reset() {
  query.keyword = "";
  query.type = "";
  query.owner = "";
  query.signedAt = "";
  query.status = "";
  pager.currentPage = 1;
}

function updateSelection(selection) {
  selectedRows.value = selection;
}

function getStatusMeta(status) {
  return statusMeta[status] || { label: status, type: "info" };
}

function goCreate() {
  router.push({
    name: "TemplateComplexDetail",
    query: { mode: "create" }
  });
}

function goDetail(row, mode = "view") {
  router.push({
    name: "TemplateComplexDetail",
    query: { id: row.id, mode }
  });
}
</script>

<template>
  <section class="jl-page-shell complex-list-page">
    <div class="jl-search-card">
      <el-form class="jl-search-form" :model="query" label-width="auto">
        <el-row :gutter="24">
          <el-col :span="6">
            <el-form-item label="签署日期">
              <el-date-picker v-model="query.signedAt" type="date" value-format="YYYY-MM-DD" placeholder="请选择" clearable />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="合同关键词">
              <el-input v-model="query.keyword" clearable placeholder="编号 / 名称 / 项目" @keyup.enter="search" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="合同类型">
              <el-select v-model="query.type" placeholder="请选择" clearable>
                <el-option v-for="item in typeOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="负责人">
              <el-input v-model="query.owner" clearable placeholder="请输入负责人" @keyup.enter="search" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="合同状态">
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
          <el-button type="primary" @click="goCreate">新增</el-button>
          <el-button :disabled="!selectedCount">批量提交</el-button>
        </div>
      </div>

      <el-table
        class="jl-standard-table"
        :data="pageRows"
        row-key="id"
        height="100%"
        @selection-change="updateSelection"
      >
        <el-table-column type="selection" width="48" />
        <el-table-column prop="code" label="合同编号" width="170" />
        <el-table-column prop="name" label="合同名称" width="220" show-overflow-tooltip />
        <el-table-column prop="type" label="合同类型" width="130" />
        <el-table-column prop="projectName" label="关联项目" width="220" show-overflow-tooltip />
        <el-table-column prop="partner" label="合作方" width="260" show-overflow-tooltip />
        <el-table-column prop="amount" label="合同金额" width="130" align="right" />
        <el-table-column prop="paidAmount" label="已到账金额" width="130" align="right" />
        <el-table-column prop="remainingAmount" label="待回款金额" width="130" align="right" />
        <el-table-column prop="owner" label="负责人" width="110" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="getStatusMeta(row.status).type">{{ getStatusMeta(row.status).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="signedAt" label="签署日期" width="130" />
        <el-table-column prop="updatedAt" label="更新时间" width="170" />
        <el-table-column label="操作" fixed="right" width="128">
          <template #default="{ row }">
            <div class="jl-table-actions">
              <el-button link type="primary" @click="goDetail(row)">详情</el-button>
              <el-button link type="primary" @click="goDetail(row, 'edit')">编辑</el-button>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <span class="jl-empty-text">暂无数据</span>
        </template>
      </el-table>

      <div class="jl-pagination-wrap">
        <el-pagination
          v-model:current-page="pager.currentPage"
          v-model:page-size="pager.pageSize"
          :page-sizes="[5, 10, 20]"
          :total="filteredRows.length"
          background
          layout="total, prev, pager, next, sizes"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
.complex-list-page {
  min-width: 960px;
}
</style>
