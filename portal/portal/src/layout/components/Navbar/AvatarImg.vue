<template>
  <div class="avatar-img">
    <img class="sys-logo" src="@/assets/images/jvlei-logo-white.svg" alt="聚垒科技" />

    <div class="sys-title">
      {{ setting.title }}
    </div>
  </div>
</template>

<script setup>
import setting from "@/setting";
</script>

<style lang="scss" scoped>
.avatar-img {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;

  .sys-logo {
    display: block;
    width: 28px;
    height: 24px;
  }
}

.sys-title {
  display: flex;
  align-items: center;
  min-width: 0;
  height: 22px;
  font-size: 18px;
  font-weight: 550;
  line-height: 22px;
  color: #fff;
  white-space: nowrap;
}
</style>
