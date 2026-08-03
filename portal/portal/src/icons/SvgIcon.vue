// SvgIcon.vue

<template>
  <svg :class="svgClass" v-bind="$attrs" :style="{ color: color, fontSize: size + 'px' }">
    <use :href="iconName"></use>
  </svg>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  name: {
    type: String,
    required: true
  },
  color: {
    type: String,
    default: ""
  },
  size: {
    type: Number,
    default: 14
  }
});
const iconName = computed(() => `#icon-${props.name}`);
const svgClass = computed(() => {
  if (props.name) return `svg-icon icon-${props.name}`;
  return "svg-icon";
});
</script>

<style scoped lang="scss">
.svg-icon {
  width: 1em;
  height: 1em;
  fill: currentColor;
  vertical-align: middle;
  outline: none;
  &:active {
    outline: none;
  }
}
</style>
