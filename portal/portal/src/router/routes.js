 import Layout from "@/layout/index.vue";
import Login from "@/views/login/login.vue";
import i18n from "@/locales/i18n";
import setting from "@/setting";

// 无需权限的页面
const constantRoutes = [
  {
    path: "/",
    name: "app-entry",
    component: () => import("@/views/loading/index.vue")
  },
  {
    path: "/login",
    name: "Login",
    meta: {
      title: i18n.global.t("route.login")
    },
    component: Login
  },
  {
    path: "/404",
    name: "404",
    meta: {
      title: "404",
      keepAlive: true
    },
    component: () => import("@/views/error/404.vue")
  },
  {
    path: "/401",
    name: "401",
    hidden: true,
    meta: {
      title: "404",
      keepAlive: true
    },
    component: () => import("@/views/error/401.vue")
  },
  // 动态路由尚未注册时保留原始 URL，避免刷新深链路丢失 hash path
  {
    path: "/:pathMatch(.*)*",
    name: "pre-loading",
    component: () => import("@/views/loading/index.vue")
  }
];

// 权限页面: 权限页全部丢到 children 里面去, 方便布局改动或是缓存的处理
// 路由会依据后端返回 routes, 自动生成; 对应了 { ...compoent(组件路径), menuName(页面名称), path(页面路由), orderNum(页面排序) } 等字段信息
const asyncRoutes = [
  {
    path: "/" + setting.appName,
    name: setting.appName,
    component: Layout,
    meta: { public: true },
    children: []
  }
];

// 前端定义页面: 会被塞到 asyncRoutes[0].children 中, 在筛选路由时, 过滤出可访问的路由
const frontDefinedRoutes = [
  {
    path: "/template-standard-list",
    name: "TemplateStandardList",
    meta: {
      title: "普通列表模板",
      public: true
    },
    component: () => import("@/views/template/StandardList.vue")
  },
  {
    path: "template-complex-list",
    name: "TemplateComplexList",
    meta: {
      title: "复杂列表模板",
      public: true
    },
    component: () => import("@/views/template/ComplexList.vue")
  },
  {
    path: "template-complex-detail",
    name: "TemplateComplexDetail",
    meta: {
      title: "复杂详情模板",
      public: true,
      activeMenuCode: "app-template-template-complex-list"
    },
    component: () => import("@/views/template/ComplexDetail.vue")
  },
  {
    path: "/template/basic-list",
    name: "TemplateBasicList",
    meta: {
      title: "基础列表",
      public: true
    },
    component: () => import("@/views/template/PlaceholderPage.vue")
  },
  {
    path: "/template/advanced-form",
    name: "TemplateAdvancedForm",
    meta: {
      title: "高级表单",
      public: true
    },
    component: () => import("@/views/template/PlaceholderPage.vue")
  },
  {
    path: "/template/detail-page",
    name: "TemplateDetailPage",
    meta: {
      title: "详情页面",
      public: true
    },
    component: () => import("@/views/template/PlaceholderPage.vue")
  },
  {
    path: "/business/dashboard",
    name: "BusinessDashboard",
    meta: {
      title: "数据看板",
      public: true
    },
    component: () => import("@/views/template/PlaceholderPage.vue")
  },
  {
    path: "/business/approval-flow",
    name: "BusinessApprovalFlow",
    meta: {
      title: "审批流程",
      public: true
    },
    component: () => import("@/views/template/PlaceholderPage.vue")
  },
  {
    path: "/business/process-config",
    name: "BusinessProcessConfig",
    meta: {
      title: "流程配置",
      public: true
    },
    component: () => import("@/views/template/PlaceholderPage.vue")
  },
  {
    path: "/system/users",
    name: "SystemUsers",
    meta: {
      title: "用户管理",
      public: true
    },
    component: () => import("@/views/template/PlaceholderPage.vue")
  },
  {
    path: "/system/roles",
    name: "SystemRoles",
    meta: {
      title: "角色权限",
      public: true
    },
    component: () => import("@/views/template/PlaceholderPage.vue")
  },
  {
    path: "/system/logs",
    name: "SystemLogs",
    meta: {
      title: "操作日志",
      public: true
    },
    component: () => import("@/views/template/PlaceholderPage.vue")
  }
];

export { constantRoutes, asyncRoutes, frontDefinedRoutes };
