<template>
  <div class="gateway-shell">
    <header class="gateway-header">
      <button
        class="mobile-menu-button"
        type="button"
        aria-label="打开导航菜单"
        @click="mobileNavOpen = true"
      >
        <el-icon><Menu /></el-icon>
      </button>
      <div class="brand">
        <div class="brand-mark">
          <img src="@/assets/images/jvlei-logo-white.svg" alt="" />
          <span>
            <b>聚垒科技</b>
            <small>JVLEI.COM</small>
          </span>
        </div>
        <span class="brand-divider"></span>
        <strong class="brand-title">设备接入采集盒配置系统</strong>
      </div>
      <el-dropdown trigger="click" @command="handleUserCommand">
        <button class="account-button" type="button">
          <span class="account-avatar"><UserFilled /></span>
          <span class="account-name">{{ session.username }}</span>
          <ArrowDown class="account-arrow" />
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="logout">
              <el-icon><SwitchButton /></el-icon>
              退出登录
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </header>

    <div class="gateway-body">
      <aside class="gateway-sidebar">
        <div class="sidebar-title">
          <span>报告采集设备</span>
          <ArrowUp class="sidebar-arrow" />
        </div>
        <nav class="sidebar-nav">
          <router-link v-for="item in navigation" :key="item.path" :to="item.path">
            <component :is="item.icon" />
            <span>{{ item.label }}</span>
          </router-link>
        </nav>
        <div class="sidebar-section">运行状态</div>
        <div class="sidebar-health">
          <span class="health-dot"></span>
          设备服务运行中
        </div>
      </aside>

      <section class="gateway-workspace">
        <div class="gateway-tabs">
          <router-link v-for="item in navigation" :key="item.path" :to="item.path">
            {{ item.label }}
          </router-link>
        </div>
        <main class="gateway-content">
          <router-view />
        </main>
      </section>
    </div>

    <el-drawer
      v-model="mobileNavOpen"
      direction="ltr"
      size="82%"
      :with-header="false"
      class="mobile-nav-drawer"
    >
      <div class="mobile-nav-panel">
        <div class="mobile-nav-heading">
          <div>
            <strong>报告采集设备</strong>
            <span>设备接入采集盒配置系统</span>
          </div>
          <button type="button" aria-label="关闭导航菜单" @click="mobileNavOpen = false">
            <el-icon><Close /></el-icon>
          </button>
        </div>
        <nav class="sidebar-nav mobile-nav-list">
          <router-link
            v-for="item in navigation"
            :key="item.path"
            :to="item.path"
            @click="mobileNavOpen = false"
          >
            <component :is="item.icon" />
            <span>{{ item.label }}</span>
          </router-link>
        </nav>
        <div class="mobile-nav-health">
          <span class="health-dot"></span>
          设备服务运行中
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import {
  ArrowDown,
  ArrowUp,
  Clock,
  Close,
  Coin,
  Connection,
  Document,
  Download,
  Menu,
  Printer,
  Setting,
  SwitchButton,
  UserFilled
} from "@element-plus/icons-vue";
import { ref } from "vue";
import { useRouter } from "vue-router";
import { useSessionStore } from "@/stores/session";

const router = useRouter();
const session = useSessionStore();
const mobileNavOpen = ref(false);

const navigation = [
  { path: "/config", label: "配置管理", icon: Setting },
  { path: "/reports", label: "报告日志", icon: Document },
  { path: "/printer", label: "模拟打印配置", icon: Printer },
  { path: "/physical-printer", label: "实体打印机配置", icon: Printer },
  { path: "/drivers", label: "实体打印驱动", icon: Printer },
  { path: "/msc", label: "模拟U盘配置", icon: Coin },
  { path: "/wifi", label: "网络配置", icon: Connection },
  { path: "/maintenance", label: "存储与清理", icon: Clock },
  { path: "/update", label: "软件升级", icon: Download }
];

async function handleUserCommand(command) {
  if (command === "logout") {
    await session.logout();
    router.replace("/login");
  }
}
</script>
