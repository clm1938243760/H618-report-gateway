<template>
  <div class="app-main">
    <main class="app-main-content">
      <router-view v-slot="{ Component, route }">
        <keep-alive v-if="route.meta.keepAlive" :include="openTags">
          <component :is="Component"></component>
        </keep-alive>

        <component :is="Component" v-else></component>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { useTagStore } from "@/stores/tags";
import { computed } from "vue";

const tagStore = useTagStore();
const openTags = computed(() => {
  return tagStore.visitedRoutes.map((v) => v.key);
});
</script>

<style lang="scss" scoped>
.app-main {
  width: 100%;
  box-sizing: border-box;
  overflow: hidden;

  .app-main-top {
    display: flex;
    align-items: center;
    flex-shrink: 0;
    height: $breadcrumbHeight;
    background: transparent;
    background-color: #fff;
    border-bottom: 0.5px solid rgba(#000, 0.05);
    box-shadow: 0 1px 8px rgba(0, 21, 41, 0.08);
  }

  .app-main-content {
    width: 100%;
    height: 100%;
    padding: 16px;
    box-sizing: border-box;
    overflow-y: auto;
    overflow-x: hidden;
    position: relative;
    background: var(--JL-color-bg-page);

    .comp-container {
      height: 100%;
      position: relative;
    }
    .app-main-content-main {
      width: 100%;
      height: 100%;
    }
  }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.slide-enter-active,
.slide-leave-active {
  transition: transform 0.3s ease;
}
.slide-enter-from {
  transform: translateX(100%);
}
.slide-leave-to {
  transform: translateX(-100%);
}
</style>
