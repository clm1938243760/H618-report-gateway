<template>
  <div class="app-main jl-app-main">
    <div class="app-main-top jl-app-main-top" v-if="visitedRoutes && visitedRoutes.length">
      <Tags />
    </div>

    <main class="app-main-content jl-app-main-content">
      <div class="jl-app-main-content-inner">
        <router-view v-slot="{ Component, route }">
          <keep-alive v-if="route.meta.keepAlive" :include="openTags">
            <component :is="Component"></component>
          </keep-alive>

          <component :is="Component" v-else></component>
        </router-view>
      </div>
    </main>
  </div>
</template>

<script setup>
import { useTagStore } from "@/stores/tags";
import Tags from "./Sidebar/Tags.vue";
import { computed } from "vue";

const tagStore = useTagStore();
const openTags = computed(() => {
  return tagStore.visitedRoutes.map((v) => v.key);
});

const visitedRoutes = computed(() => {
  return tagStore.visitedRoutes;
});
</script>

<style lang="scss" scoped>
.app-main {
  .app-main-top {
    height: $breadcrumbHeight;
  }

  .app-main-content {
    height: $adminContentHeight;

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
