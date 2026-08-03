<template>
  <div class="layout-section-tag" v-if="visitedRoutes && visitedRoutes.length">
    <Tags />
  </div>
</template>

<script setup>
import { useTagStore } from "@/stores/tags";
import Tags from "./Sidebar/Tags.vue";
import { computed, ref } from "vue";

const tagStore = useTagStore();

const visitedRoutes = computed(() => {
  return tagStore.visitedRoutes;
});

const openTags = computed(() => {
  return tagStore.visitedRoutes.map((v) => v.key); // .filter(v => v !== closedTag.value)
});
</script>
