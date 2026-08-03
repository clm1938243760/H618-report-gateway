<template>
  <div class="loading-overlay" v-if="isLoading">
    <div class="loading-container">
      <!-- 脉冲点动画 -->
      <div class="pulse-dots">
        <div class="dot" :style="{ animationDelay: '0ms' }"></div>
        <div class="dot" :style="{ animationDelay: '150ms' }"></div>
        <div class="dot" :style="{ animationDelay: '300ms' }"></div>
        <div class="dot" :style="{ animationDelay: '450ms' }"></div>
      </div>

      <!-- 加载文本 -->
      <p class="loading-text">{{ loadingText }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, defineProps, watch } from "vue";

// 配置选项
const props = defineProps({
  loadingText: {
    type: String,
    default: "加载中..."
  },
  show: {
    type: Boolean,
    default: true
  }
});

const isLoading = ref(props.show);

// 监听外部传入的show状态
watch(
  () => props.show,
  (newVal) => {
    isLoading.value = newVal;
  }
);
</script>

<style lang="scss" scoped>
// 变量配置
$primary-color: #409eff; // 主色调
$text-color: #333; // 文本颜色
$bg-color: rgba(255, 255, 255, 0.8); // 背景色
$dot-size: 10px; // 圆点大小
$dot-spacing: 8px; // 圆点间距
$animation-duration: 1.2s; // 动画周期

.loading-overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  background-color: $bg-color;
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1;
  backdrop-filter: blur(2px); // 毛玻璃效果
}

.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.pulse-dots {
  display: flex;
  align-items: center;
  margin-bottom: 24px;
}

.dot {
  width: $dot-size;
  height: $dot-size;
  border-radius: 50%;
  background-color: $primary-color;
  margin: 0 calc($dot-spacing/2);
  opacity: 0.3;

  // 脉冲动画
  animation: pulse $animation-duration infinite ease-in-out;

  // 防止闪烁
  backface-visibility: hidden;
}

// 文本样式
.loading-text {
  font-size: 16px;
  color: $text-color;
  letter-spacing: 0.5px;
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, sans-serif;
}

// 脉冲动画
@keyframes pulse {
  0% {
    transform: scale(0.8);
    opacity: 0.3;
  }
  50% {
    transform: scale(1.2);
    opacity: 1;
  }
  100% {
    transform: scale(0.8);
    opacity: 0.3;
  }
}
</style>
