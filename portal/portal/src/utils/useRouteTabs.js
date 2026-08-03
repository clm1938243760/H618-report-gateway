import { useRoute, useRouter } from "vue-router";
import { useTagStore } from "@/stores/tags";

export function useRouteTabs() {
  const route = useRoute();
  const router = useRouter();
  const tagStore = useTagStore();

  function closeCurrentTab(fallbackLocation) {
    const nextRoute = tagStore.DELETE_VISITED_ROUTE({ path: route.path });

    if (nextRoute) {
      router.push({ path: nextRoute.path, query: nextRoute.query });
      return;
    }

    if (fallbackLocation) {
      router.push(fallbackLocation);
    }
  }

  return {
    closeCurrentTab
  };
}
