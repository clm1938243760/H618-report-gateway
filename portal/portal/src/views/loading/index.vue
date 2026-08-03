<template>
  <div class="route-loading-page">
    <LoadingComponent :show="true" loadingText="加载中..." />
  </div>
</template>

<script setup>
import LoadingComponent from "./loading.vue";
</script>

<style scoped>
.route-loading-page {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 240px;
}
</style>
