<template>
  <el-menu-item v-if="isNullOrEmpty(route.children)" :index="route.path" :key="route.path + '_no_children'" @click="addCurrentRouteToTag(route)">
    <span v-if="getResolvedIcon(route.icon, level)" class="menu-icon" :style="getIconStyle(getResolvedIcon(route.icon, level))"></span>
    <template #title>{{ route.menuName }}</template>
  </el-menu-item>

  <template v-else>
    <template v-if="hasSingleChild(route)">
      <el-menu-item :index="route.children[0].path" :key="route.path + '-' + route.children[0].path" @click="addCurrentRouteToTag(route.children[0])">
        <span
          v-if="getResolvedIcon(route.children[0]?.icon, level)"
          class="menu-icon"
          :style="getIconStyle(getResolvedIcon(route.children[0]?.icon, level))"
        ></span>
        <template #title>{{ route.children[0].menuName }}</template>
      </el-menu-item>
    </template>
    <el-sub-menu v-else popper-class="custom-popper" :index="subMenuIndex(route)" :key="subMenuKey(route) + '_more_children'">
      <template #title>
        <span v-if="getResolvedIcon(route.icon, level)" class="menu-icon" :style="getIconStyle(getResolvedIcon(route.icon, level))"></span>
        <span>{{ route.menuName }}</span>
      </template>

      <MenuItem v-for="child in route.children" :key="child.path" :route="child" :level="level + 1" />
    </el-sub-menu>
  </template>
</template>

<script setup>
import { useTagStore } from "@/stores/tags";
import { convertToCamelCase } from "@/utils/tool";
import { useRouter } from "vue-router";
import { getToken } from "@/utils/token";
import defaultTopMenuIcon from "@/icons/nav-bar/default.svg";

const tagStore = useTagStore();

defineProps({
  route: {
    type: Object,
    default: () => ({})
  },
  level: {
    type: Number,
    default: 1
  }
});

function isNullOrEmpty(val) {
  if (typeof val == "boolean") {
    return false;
  }
  if (typeof val == "number") {
    return false;
  }
  if (val instanceof Array) {
    if (val.length == 0) return true;
  } else if (val instanceof Object) {
    if (JSON.stringify(val) === "{}") return true;
  } else {
    if (val == "null" || val == null || val == "undefined" || val == undefined || val == "") return true;
    return false;
  }
  return false;
}

function subMenuKey(route) {
  if (route == null) {
    return "sub";
  }
  if (route.menuId != null && String(route.menuId) !== "") {
    return `menu-${route.menuId}`;
  }
  const path = String(route.path ?? "").trim();
  if (path) {
    return path;
  }
  return `sub-${route.menuName || "item"}`;
}

function subMenuIndex(route) {
  return subMenuKey(route);
}

const hasSingleChild = () => {
  return false;
};

function resolveUrlWithVue(path, hash, params) {
  const url = new URL(path);
  const search = new URLSearchParams(url.search);
  let searchStr = "";

  if (params) {
    for (const key in params) {
      search.set(key, params[key]);
    }
  }
  searchStr = search.toString() ? `?${search.toString()}` : "";

  return url.origin + url.pathname + (hash ? `#${hash}` : url.hash || "") + searchStr;
}

function getIconStyle(icon) {
  const imageUrl = `url("${icon}")`;
  return {
    maskImage: imageUrl,
    WebkitMaskImage: imageUrl
  };
}

function getResolvedIcon(icon, level) {
  if (icon) {
    return icon;
  }
  return level === 1 ? defaultTopMenuIcon : "";
}

const router = useRouter();
const addCurrentRouteToTag = (curRoute) => {
  const { innerOpen, transAuth, routeType, routeUrl, path } = curRoute;

  if (innerOpen == "0") {
    if (routeType === "out-absolute-page") {
      window.open(resolveUrlWithVue(routeUrl, "", transAuth == 1 ? { token: getToken() } : {}));
    } else {
      window.open(resolveUrlWithVue(location.href, path, transAuth == 1 ? { token: getToken() } : {}));
    }
  } else {
    router.push({ path });

    const routeName = curRoute.menuName;
    tagStore.ADD_VISITED_ROUTE({
      path,
      name: routeName,
      key: convertToCamelCase(path),
      meta: {}
    });
  }
};
</script>

<style lang="less" scoped>
.menu-icon {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  margin-right: 12px;
  background-color: currentColor;
  mask-repeat: no-repeat;
  mask-position: center;
  mask-size: contain;
  -webkit-mask-repeat: no-repeat;
  -webkit-mask-position: center;
  -webkit-mask-size: contain;
}
</style>
