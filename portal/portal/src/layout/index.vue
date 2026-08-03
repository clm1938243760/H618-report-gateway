<template>
  <div class="layout">
    <template v-if="isRunningInRegularWindow">
      <template v-if="layoutPlan === 'default'">
        <Navbar class="layout-nav" />
        <section class="layout-main">
          <Sidebar class="layout-sidebar" />
          <AppMain class="layout-container"></AppMain>
        </section>
      </template>
      <template v-else-if="layoutPlan === 'horizontalWithLabels'">
        <Navbar class="layout-h-nav">
          <AppMenu direction="horizontal"></AppMenu>
        </Navbar>
        <TagPure class="layout-h-tag"></TagPure>
        <AppMainPure class="layout-h-appMain" />
      </template>
      <template v-else-if="layoutPlan === 'horizontalNoLabel'">
        <Navbar class="layout-h-nav">
          <AppMenu direction="horizontal"></AppMenu>
        </Navbar>
        <AppMainPure class="layout-h-appMain" />
      </template>
    </template>
    <template v-else>
      <AppMainPure class="layout-h-appMain" />
    </template>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useGetters } from "@/stores/getter";

import Navbar from "./components/Navbar/index.vue";
import AppMain from "./components/AppMain.vue";
import Sidebar from "./components/Sidebar/index.vue";
import AppMainPure from "./components/AppMainPure.vue";
import TagPure from "./components/TagPure.vue";
import AppMenu from "./components/Sidebar/Menu.vue";
import setting from "@/setting";

const isRunningInRegularWindow = setting.appRuntimeWindowObject === "window";
const Getter = useGetters();
const sideBarWidth = "180px";
const layoutPlan = computed(() => Getter.layoutPlan);
</script>

<style lang="scss" scoped>
.layout {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  position: relative;

  .layout-main {
    width: 100%;
    height: calc(100vh - $appHeaderHeight);
    display: flex;

    .layout-sidebar {
      width: v-bind(sideBarWidth);
      flex-shrink: 0;
    }

    .layout-container {
      flex: 1;
      min-width: 0;
    }
  }

  .layout-h-tag {
    height: $breadcrumbHeight;
  }
  .layout-h-appMain {
    flex: 1;
  }
}
</style>
