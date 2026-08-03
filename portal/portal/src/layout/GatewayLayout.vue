<template>
  <div class="gateway-shell">
    <header class="gateway-header">
      <div class="brand">
        <div class="brand-mark">
          <img src="@/assets/images/jvlei-logo-white.svg" alt="" />
          <span>
            <b>聚垒科技</b>
            <small>JVLEI.COM</small>
          </span>
        </div>
        <span class="brand-divider"></span>
        <strong>设备接入采集盒配置系统</strong>
      </div>
      <el-dropdown trigger="click" @command="handleUserCommand">
        <button class="account-button" type="button">
          <span class="account-avatar"><UserFilled /></span>
          <span>{{ session.username }}</span>
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
  </div>
</template>

<script setup>
import {
  ArrowDown,
  ArrowUp,
  Clock,
  Document,
  Setting,
  SwitchButton,
  UserFilled
} from "@element-plus/icons-vue";
import { useRouter } from "vue-router";
import { useSessionStore } from "@/stores/session";

const router = useRouter();
const session = useSessionStore();

const navigation = [
  { path: "/config", label: "配置管理", icon: Setting },
  { path: "/reports", label: "报告日志", icon: Document },
  { path: "/maintenance", label: "存储与清理", icon: Clock }
];

async function handleUserCommand(command) {
  if (command === "logout") {
    await session.logout();
    router.replace("/login");
  }
}
</script>
