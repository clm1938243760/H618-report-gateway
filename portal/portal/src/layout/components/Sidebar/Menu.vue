<template>
  <el-menu
    class="custom-menu-container"
    :class="{ horizontal: props.direction === 'horizontal' }"
    :default-active="activeMenu"
    :background-color="props.direction === 'vertical' ? '#fff' : 'transparent'"
    text-color="var(--JL-color-text-regular)"
    active-text-color="var(--JL-color-primary)"
    :mode="props.direction"
  >
    <template v-for="(route, index) in formattedRoutes" :key="route.menuId || route.path || index">
      <MenuItem :route="route" :level="1"></MenuItem>
    </template>
  </el-menu>
</template>

<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { useTagStore } from "@/stores/tags";
import { getAccessRoutes, getMenus } from "@/router/index";
import { convertToCamelCase, findNodeInTree } from "@/utils/tool";
import setting from "@/setting";
import MenuItem from "./MenuItem.vue";

const tagStore = useTagStore();

const props = defineProps({
  direction: {
    type: String,
    default: "vertical"
  }
});

const currentRoute = useRoute();
const formattedRoutes = computed(() => getMenus());
const activeMenu = computed(() => {
  const activeMenuCode = currentRoute.meta?.activeMenuCode;
  if (activeMenuCode) {
    const matchedMenu = findMenuByCode(formattedRoutes.value, activeMenuCode);
    if (matchedMenu?.path) {
      return matchedMenu.path;
    }
  }

  return currentRoute.meta?.activeMenu || currentRoute.path;
});

if (currentRoute.path === setting.appName) {
} else {
  const initPage = findMatchRouteByFullPath(currentRoute.path);

  tagStore.ADD_VISITED_ROUTE({
    path: currentRoute.path,
    name: initPage ? getRouteName(initPage) : "",
    key: convertToCamelCase(currentRoute.path)
  });
}

function findMatchRouteByFullPath(fullPath) {
  const allAccRoutes = getAccessRoutes();
  const node = findNodeInTree(
    allAccRoutes,
    (node) => {
      const { path } = node;
      return path === fullPath;
    },
    "children"
  );

  return node;
}

function getRouteName(curRoute) {
  let routeName = curRoute.meta?.title;
  if (!routeName && curRoute.children && curRoute.children.length) {
    routeName = curRoute.children[0].meta?.title;
  }
  return routeName;
}

function findMenuByCode(menus, menuCode) {
  return findNodeInTree(
    menus,
    (node) => {
      return node.menuCode === menuCode;
    },
    "children"
  );
}
</script>

<style lang="scss" scoped>
$menu-text-color: #1d2129;
$menu-sub-text-color: #4e5969;
$menu-muted-color: #86909c;
$menu-active-color: #0097e9;
$menu-active-indicator-color: #009ae9;
$menu-active-bg: rgba(0, 151, 233, 0.08);
$menu-item-height: 44px;
$menu-item-padding-x: 16px;
$menu-icon-size: 16px;
$menu-icon-gap: 12px;
$sub-menu-item-padding-left: $menu-item-padding-x + $menu-icon-size + $menu-icon-gap;

.custom-popper {
  .#{$namespace}-menu.#{$namespace}-menu-item {
    color: $menu-text-color;
  }
}

.custom-menu-container {
  width: 100%;
  background-color: #fff;

  .#{$namespace}-sub-menu .#{$namespace}-menu {
    .#{$namespace}-menu-item {
      padding-left: $menu-item-padding-x;
    }
  }
}

.custom-menu-container.#{$namespace}-menu {
  border-right: none;

  :deep(.#{$namespace}-menu-item) {
    position: relative;
    height: $menu-item-height;
    padding: 0 $menu-item-padding-x !important;
    font-size: 14px;
    font-weight: 400;
    line-height: 22px;
    display: flex;
    align-items: center;
    color: $menu-text-color;
    background-color: #fff;
    text-overflow: ellipsis;
    overflow: hidden;
    white-space: nowrap;
    box-sizing: border-box;

    &:hover {
      background-color: $menu-active-bg !important;
    }

    .#{$namespace}-menu-tooltip__trigger {
      padding: 0;
      margin: 0;
    }

    .menu-icon {
      width: $menu-icon-size;
      height: $menu-icon-size;
      margin-right: $menu-icon-gap;
      object-fit: contain;
      display: inline-block;
      flex-shrink: 0;
    }
  }

  :deep(.#{$namespace}-menu-item.is-active) {
    color: $menu-active-color;
    background-color: $menu-active-bg !important;

    &::after {
      content: "";
      position: absolute;
      top: 0;
      right: 0;
      width: 2px;
      height: $menu-item-height;
      background-color: $menu-active-indicator-color;
    }

    .menu-icon {
      color: $menu-active-color;
    }
  }

  :deep(.#{$namespace}-sub-menu) {
    .#{$namespace}-sub-menu__title {
      height: $menu-item-height;
      padding: 0 $menu-item-padding-x !important;
      font-size: 14px;
      font-weight: 400;
      line-height: 22px;
      color: $menu-text-color;
      background-color: #fff;
      display: flex;
      align-items: center;
      position: relative;

      &:hover {
        background-color: $menu-active-bg !important;
      }

      .menu-icon {
        width: $menu-icon-size;
        height: $menu-icon-size;
        margin-right: $menu-icon-gap;
      }
    }

    &.is-active > .#{$namespace}-sub-menu__title {
      color: $menu-text-color;
      background-color: #fff !important;
    }

    .#{$namespace}-sub-menu__icon-arrow {
      right: $menu-item-padding-x;
      color: $menu-muted-color;
      font-size: 14px;
    }

    .#{$namespace}-menu.#{$namespace}-menu-item {
      background-color: #fff;
      &:hover {
        background-color: $menu-active-bg !important;
      }
    }

    .#{$namespace}-menu-item {
      padding-left: $sub-menu-item-padding-left !important;
      font-weight: 400;
      &:not(.is-active) {
        color: $menu-sub-text-color;
      }
    }
  }

  &.horizontal {
    border-bottom: none;

    :deep(.#{$namespace}-sub-menu__title),
    :deep(.#{$namespace}-menu-item) {
      height: $appHeaderHeight;
      color: rgba(255, 255, 255, 0.9);
      background-color: transparent !important;

      &:hover {
        color: #fff;
        background-color: rgba(255, 255, 255, 0.12) !important;
      }
    }

    :deep(.#{$namespace}-sub-menu) {
      &.is-active {
        .#{$namespace}-sub-menu__title {
          border-bottom: none;
        }
      }
    }
    :deep(.#{$namespace}-menu-item) {
      &.is-active {
        border-bottom: none;
        color: #fff;
        background-color: rgba(255, 255, 255, 0.12) !important;

        &::after {
          display: none;
        }
      }
      &:not(.is-disabled):focus {
        background-color: transparent;
      }
    }
  }
}
</style>
