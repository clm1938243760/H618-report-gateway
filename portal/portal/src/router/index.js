import { createRouter, createWebHashHistory } from "vue-router";
import { useSessionStore } from "@/stores/session";
import { pinia } from "@/stores";

const routes = [
  {
    path: "/login",
    name: "login",
    component: () => import("@/views/login/login.vue"),
    meta: { public: true, title: "登录" }
  },
  {
    path: "/",
    component: () => import("@/layout/GatewayLayout.vue"),
    redirect: "/config",
    children: [
      {
        path: "config",
        name: "config",
        component: () => import("@/views/gateway/ConfigView.vue"),
        meta: { title: "配置管理" }
      },
      {
        path: "reports",
        name: "reports",
        component: () => import("@/views/gateway/ReportsView.vue"),
        meta: { title: "报告日志" }
      },
      {
        path: "maintenance",
        name: "maintenance",
        component: () => import("@/views/gateway/MaintenanceView.vue"),
        meta: { title: "存储与清理" }
      }
    ]
  },
  { path: "/:pathMatch(.*)*", redirect: "/config" }
];

const router = createRouter({
  history: createWebHashHistory(),
  routes
});

router.beforeEach(async (to) => {
  const session = useSessionStore(pinia);
  const loginBootstrap =
    !session.initialized &&
    window.location.pathname === "/login" &&
    ["", "#/", "#/login"].includes(window.location.hash);
  if (loginBootstrap) {
    session.initializeAnonymous();
    return "/login";
  }
  const publicRoute = to.path === "/login" || Boolean(to.meta.public);
  if (!session.initialized) {
    if (publicRoute) {
      session.initializeAnonymous();
    } else {
      await session.restore();
    }
  }
  if (publicRoute) {
    return session.authenticated ? "/config" : true;
  }
  return session.authenticated ? true : "/login";
});

router.afterEach(() => {
  document.title = "设备接入采集盒配置系统";
});

export default router;
