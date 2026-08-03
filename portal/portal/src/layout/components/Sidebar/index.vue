<template>
  <div class="sidebar-container">
    <el-scrollbar wrap-class="scrollbar-wrapper">
      <AppMenu />
    </el-scrollbar>
  </div>
</template>

<script setup>
import AppMenu from "./Menu.vue";
</script>

<style lang="scss" scoped>
.sidebar-container {
  width: 100%;
  height: calc(100vh - $appHeaderHeight);
  background-color: #fff;
  border-right: 1px solid var(--JL-color-neutral-3);
  box-sizing: border-box;
  box-shadow: 4px 0 16px rgba(134, 144, 156, 0.1);
  position: relative;
  z-index: 2;

  :deep(.#{$namespace}-scrollbar) {
    .scrollbar-wrapper {
      overflow-x: hidden !important;
    }
  }
}
</style>
