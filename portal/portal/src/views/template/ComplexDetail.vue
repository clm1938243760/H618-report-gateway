<script setup>
import { computed, reactive } from "vue";
import { ElMessage } from "element-plus";
import { useRoute, useRouter } from "vue-router";
import { useRouteTabs } from "@/utils/useRouteTabs";

const route = useRoute();
const router = useRouter();
const { closeCurrentTab } = useRouteTabs();

const contracts = [
  {
    id: "2049736613293502465",
    code: "TJ-CGB-2026-0002",
    name: "测试合同",
    type: "专利权转让",
    projectName: "智慧病区数据治理项目",
    projectCode: "123",
    signedAt: "2026-04-30",
    amount: "100,000.00",
    partner: "甲方：1111；乙方：123",
    paidAmount: "100,000.00",
    distributableAmount: "100,000.00",
    remainingAmount: "0.00",
    owner: "王建",
    department: "成果转化办公室",
    status: "执行中",
    remark: "适用于合同字段较多、附件和流程信息需要分区展示的二级详情页面。"
  },
  {
    id: "2049736613293502466",
    code: "TJ-CGB-2026-0003",
    name: "科研成果转化服务合同",
    type: "技术服务",
    projectName: "院内科研服务协同平台",
    projectCode: "JL-PROJ-2026-003",
    signedAt: "2026-05-02",
    amount: "86,500.00",
    partner: "甲方：津莱医院；乙方：华北技术服务中心",
    paidAmount: "20,000.00",
    distributableAmount: "20,000.00",
    remainingAmount: "66,500.00",
    owner: "李思",
    department: "科研管理部",
    status: "审批中",
    remark: "二级页面可以承载较长表单、附件、审批和回款计划。"
  }
];

const attachmentRows = [
  {
    id: "att-001",
    name: "合同正文.pdf",
    format: "PDF",
    size: "1.8 MB",
    uploadedAt: "2026-04-30 10:20"
  },
  {
    id: "att-002",
    name: "付款计划.xlsx",
    format: "XLSX",
    size: "642 KB",
    uploadedAt: "2026-04-30 10:24"
  }
];

const processRows = [
  {
    id: "flow-001",
    node: "合同拟定",
    operator: "王建",
    result: "提交",
    handledAt: "2026-04-28 09:30"
  },
  {
    id: "flow-002",
    node: "部门审核",
    operator: "李思",
    result: "通过",
    handledAt: "2026-04-29 14:12"
  },
  {
    id: "flow-003",
    node: "合同归档",
    operator: "赵敏",
    result: "归档",
    handledAt: "2026-04-30 16:45"
  }
];

const mode = computed(() => {
  const value = route.query.mode;
  return value === "create" || value === "edit" ? value : "view";
});

const isFormMode = computed(() => mode.value === "create" || mode.value === "edit");
const contractId = computed(() => (typeof route.query.id === "string" ? route.query.id : ""));
const currentContract = computed(() => contracts.find((item) => item.id === contractId.value) || contracts[0]);

const form = reactive({
  code: currentContract.value.code,
  name: currentContract.value.name,
  type: currentContract.value.type,
  projectName: currentContract.value.projectName,
  projectCode: currentContract.value.projectCode,
  signedAt: currentContract.value.signedAt,
  amount: currentContract.value.amount,
  partner: currentContract.value.partner,
  owner: currentContract.value.owner,
  department: currentContract.value.department,
  remark: currentContract.value.remark
});

const basicRows = computed(() => [
  [
    { label: "合同编号", value: currentContract.value.code },
    { label: "合同名称", value: currentContract.value.name }
  ],
  [
    { label: "合同类型", value: currentContract.value.type },
    { label: "关联项目", value: currentContract.value.projectCode, link: true }
  ],
  [
    { label: "签署日期", value: currentContract.value.signedAt },
    { label: "合同金额", value: currentContract.value.amount }
  ],
  [
    { label: "合作方", value: currentContract.value.partner },
    { label: "已到账金额", value: currentContract.value.paidAmount }
  ],
  [
    { label: "可分配金额", value: currentContract.value.distributableAmount },
    { label: "待回款金额", value: currentContract.value.remainingAmount }
  ],
  [
    { label: "负责人", value: currentContract.value.owner },
    { label: "所属部门", value: currentContract.value.department }
  ],
  [
    { label: "合同状态", value: currentContract.value.status },
    { label: "备注", value: currentContract.value.remark }
  ]
]);

function goBack() {
  router.push({ name: "TemplateComplexList" });
}

function closePage() {
  closeCurrentTab({ name: "TemplateComplexList" });
}

function save() {
  ElMessage.success("保存成功");
  router.push({
    name: "TemplateComplexDetail",
    query: {
      id: contractId.value || "2049736613293502465",
      mode: "view"
    }
  });
}
</script>

<template>
  <section class="jl-page-shell jl-page-shell--with-fixed-actions complex-detail-page">
    <template v-if="!isFormMode">
      <div class="jl-card-shell complex-detail-card">
        <h2 class="complex-detail-section-title">基本信息</h2>
        <div class="jl-detail-grid">
          <template v-for="(row, rowIndex) in basicRows" :key="rowIndex">
            <template v-for="item in row" :key="`${rowIndex}-${item.label}`">
              <div class="jl-detail-grid__label">{{ item.label }}</div>
              <div class="jl-detail-grid__value">
                <el-button v-if="item.link" link type="primary">{{ item.value }}</el-button>
                <span v-else>{{ item.value }}</span>
              </div>
            </template>
          </template>
        </div>
      </div>

      <div class="jl-card-shell complex-detail-card">
        <h2 class="complex-detail-section-title">合同附件</h2>
        <el-table class="jl-standard-table complex-detail-table" :data="attachmentRows" row-key="id">
          <el-table-column prop="name" label="附件名称" min-width="240" />
          <el-table-column prop="format" label="格式" width="140" />
          <el-table-column prop="size" label="大小" width="140" />
          <el-table-column prop="uploadedAt" label="上传时间" width="180" />
          <el-table-column label="操作" width="160">
            <template #default>
              <div class="jl-table-actions">
                <el-button link type="primary">预览</el-button>
                <el-button link type="primary">下载</el-button>
              </div>
            </template>
          </el-table-column>
          <template #empty>
            <span class="jl-empty-text">暂无数据</span>
          </template>
        </el-table>
      </div>

      <div class="jl-card-shell complex-detail-card">
        <h2 class="complex-detail-section-title">流程记录</h2>
        <el-table class="jl-standard-table complex-detail-table" :data="processRows" row-key="id">
          <el-table-column prop="node" label="节点" min-width="180" />
          <el-table-column prop="operator" label="处理人" width="140" />
          <el-table-column prop="result" label="处理结果" width="140" />
          <el-table-column prop="handledAt" label="处理时间" width="180" />
        </el-table>
      </div>
    </template>

    <template v-else>
      <el-form class="complex-detail-form" :model="form" label-width="auto">
        <div class="jl-card-shell complex-detail-card">
          <h2 class="complex-detail-section-title">合同信息</h2>
          <el-row :gutter="24">
            <el-col :span="12">
              <el-form-item label="合同编号">
                <el-input v-model="form.code" placeholder="请输入合同编号" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="合同名称">
                <el-input v-model="form.name" placeholder="请输入合同名称" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="合同类型">
                <el-select v-model="form.type" placeholder="请选择合同类型">
                  <el-option label="技术开发" value="技术开发" />
                  <el-option label="专利权转让" value="专利权转让" />
                  <el-option label="技术服务" value="技术服务" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="签署日期">
                <el-date-picker v-model="form.signedAt" type="date" value-format="YYYY-MM-DD" placeholder="请选择签署日期" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="关联项目">
                <el-input v-model="form.projectName" placeholder="请输入关联项目" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="项目编号">
                <el-input v-model="form.projectCode" placeholder="请输入项目编号" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="合同金额">
                <el-input v-model="form.amount" placeholder="请输入合同金额" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="负责人">
                <el-input v-model="form.owner" placeholder="请输入负责人" />
              </el-form-item>
            </el-col>
            <el-col :span="24">
              <el-form-item label="合作方">
                <el-input v-model="form.partner" placeholder="请输入合作方" />
              </el-form-item>
            </el-col>
            <el-col :span="24">
              <el-form-item label="备注">
                <el-input v-model="form.remark" type="textarea" :rows="4" placeholder="请输入备注" />
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <div class="jl-card-shell complex-detail-card">
          <h2 class="complex-detail-section-title">附件信息</h2>
          <el-table class="jl-standard-table complex-detail-table" :data="attachmentRows" row-key="id">
            <el-table-column prop="name" label="附件名称" min-width="240" />
            <el-table-column prop="format" label="格式" width="140" />
            <el-table-column prop="size" label="大小" width="140" />
            <el-table-column prop="uploadedAt" label="上传时间" width="180" />
            <el-table-column label="操作" width="120">
              <template #default>
                <el-button link type="danger">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-form>
    </template>

    <div class="jl-page-fixed-actions">
      <el-button v-if="!isFormMode" class="jl-button-auxiliary" @click="closePage">关闭</el-button>
      <el-button v-if="!isFormMode" type="primary"
        @click="router.push({ name: 'TemplateComplexDetail', query: { id: contractId, mode: 'edit' } })">编辑</el-button>
      <el-button v-if="isFormMode" class="jl-button-auxiliary" @click="goBack">取消</el-button>
      <el-button v-if="isFormMode" type="primary" @click="save">保存</el-button>
    </div>
  </section>
</template>

<style scoped>
.complex-detail-page {
  min-width: 960px;
  overflow: auto;
}

.complex-detail-card {
  padding: 24px;
}

.complex-detail-section-title {
  margin: 0 0 20px;
  color: var(--JL-color-text-primary);
  font-size: var(--JL-font-size-md);
  font-weight: var(--JL-font-weight-semibold);
  line-height: 24px;
}

.complex-detail-table {
  height: auto;
}

.complex-detail-form .el-row {
  row-gap: 16px;
}

.complex-detail-form .el-form-item {
  margin-bottom: 0;
}

.complex-detail-form .el-date-editor.el-input {
  width: 100%;
}
</style>
