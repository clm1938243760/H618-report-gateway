<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();

const pageTitle = computed(() => route.meta?.title || "模板页面");
const pagePath = computed(() => route.path);
</script>

<template>
  <section class="jl-page-shell placeholder-page">
    <div class="placeholder-page__panel">
      <div class="placeholder-page__header">
        <span class="placeholder-page__eyebrow">页面占位</span>
        <h1>{{ pageTitle }}</h1>
        <p>{{ pagePath }}</p>
      </div>

      <div class="placeholder-page__grid">
        <div class="placeholder-page__item">
          <span>菜单状态</span>
          <strong>已接入</strong>
        </div>
        <div class="placeholder-page__item">
          <span>页面类型</span>
          <strong>模板示例</strong>
        </div>
        <div class="placeholder-page__item">
          <span>内容区域</span>
          <strong>待扩展</strong>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.placeholder-page {
  min-width: 960px;
}

.placeholder-page__panel {
  min-height: 420px;
  padding: 32px;
  border: 1px solid var(--JL-border-color-light, #e4e7ed);
  border-radius: 6px;
  background: #fff;
}

.placeholder-page__header {
  max-width: 720px;
}

.placeholder-page__eyebrow {
  display: inline-flex;
  margin-bottom: 12px;
  color: var(--JL-color-primary);
  font-size: 14px;
  line-height: 22px;
}

.placeholder-page__header h1 {
  margin: 0;
  color: var(--JL-color-text-primary, #303133);
  font-size: 24px;
  font-weight: 600;
  line-height: 34px;
}

.placeholder-page__header p {
  margin: 8px 0 0;
  color: var(--JL-color-text-secondary, #909399);
  font-size: 14px;
  line-height: 22px;
}

.placeholder-page__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 32px;
}

.placeholder-page__item {
  padding: 18px 20px;
  border: 1px solid var(--JL-border-color-lighter, #ebeef5);
  border-radius: 6px;
  background: var(--JL-fill-color-blank, #fff);
}

.placeholder-page__item span {
  display: block;
  color: var(--JL-color-text-secondary, #909399);
  font-size: 13px;
  line-height: 20px;
}

.placeholder-page__item strong {
  display: block;
  margin-top: 8px;
  color: var(--JL-color-text-primary, #303133);
  font-size: 18px;
  font-weight: 600;
  line-height: 26px;
}
</style>
