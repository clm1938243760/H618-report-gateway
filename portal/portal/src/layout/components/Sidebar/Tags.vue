<template>
  <div id="tags-view-container" class="tags-view-container" @contextmenu="onContextMenuClick">
    <div class="nav-bar flex-aside" v-if="visitedRoutes && visitedRoutes.length">
      <el-tabs v-model="tabsActive" type="card" closable stretch class="demo-tabs" @tab-change="onTabsSwitch" @tab-remove="onTabsDelete">
        <el-tab-pane v-for="(item, index) in visitedRoutes" :key="item.path" :label="item.name" :name="index"></el-tab-pane>
      </el-tabs>

      <el-tooltip v-if="visitedRoutes?.length" content="关闭全部" placement="bottom" effect="dark">
        <button class="close-all aside" type="button" aria-label="关闭全部" @click="closeAll">
          <el-icon><CloseBold /></el-icon>
        </button>
      </el-tooltip>
    </div>
  </div>
</template>

<script setup>
import { useRoute, useRouter } from "vue-router";
import { useTagStore } from "@/stores/tags";
import { computed, watch, ref } from "vue";
import { CloseBold } from "@element-plus/icons-vue";

const route = useRoute();
const router = useRouter();

const tagStore = useTagStore();
const visitedRoutes = computed(() => {
  return tagStore.visitedRoutes;
});
const currentTag = computed(() => {
  return tagStore.viewIndex;
});

const tabsActive = ref(tagStore.viewIndex);
watch(
  () => currentTag.value,
  (index) => {
    tabsActive.value = index;
  },
  { immediate: true }
);

const jumpTo = () => {
  if (visitedRoutes.value.length === 0) {
    let defaultPage;
    const routes = router.getRoutes();

    if (routes.find((item) => item.path === "/")) {
      defaultPage = "/";
    } else {
      defaultPage = routes[0]?.path;
    }

    router.push(defaultPage);
  } else {
    const curRoute = visitedRoutes.value[currentTag.value];

    router.push({ path: curRoute.path, query: curRoute.query });
  }
};

const closeAll = () => {
  tagStore.DELETE_ALL();
  jumpTo();
};

// 标签切换
const onTabsSwitch = (args) => {
  tagStore.SELECT_VIEW(args);
  jumpTo();
};

// 删除标签
const onTabsDelete = (index) => {
  tagStore.DELETE_VISITED_ROUTE(+index);
  jumpTo();
};
</script>

<style lang="scss" scoped>
$tabHeight: 44px;
@mixin flexAside() {
  display: flex;
  justify-content: space-between;
  > .aside {
    flex-shrink: 0;
  }
  > .content {
    flex: 1;
  }
}

.tags-view-container {
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  width: 100%;
  height: $tabHeight;
  background: #fff;
  box-shadow: 0 4px 16px rgba(#86909c, 0.1);
  position: relative;
  z-index: 1;

  .nav-bar {
    overflow: hidden;
    height: $tabHeight;
    border-bottom: 1px solid var(--JL-color-neutral-3);
  }

  :deep(.#{$namespace}-tabs) {
    height: $tabHeight;

    .#{$namespace}-tabs__header {
      height: $tabHeight;
      margin: 0;
    }

    .#{$namespace}-tabs__content {
      display: none;
    }

    .#{$namespace}-tabs__nav-scroll,
    .#{$namespace}-tabs__nav-wrap,
    .#{$namespace}-tabs__nav {
      height: $tabHeight;
    }

    .#{$namespace}-tabs__item {
      display: flex;
      align-items: center;
      border: none;
      border-radius: 0;
      height: $tabHeight;
      line-height: 22px;
      text-align: center;
      user-select: none;
      font-weight: 400;

      &::after {
        content: "";
        position: absolute;
        top: 0;
        right: 0;
        bottom: -1px;
        width: 1px;
        background: var(--JL-color-neutral-3);
      }

      &:hover {
        color: $color-blue;
      }

      .is-icon-close {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        position: static;
        right: auto;
        width: 0;
        height: 14px;
        margin-left: 0;
        font-size: 14px;
        line-height: 1;
        color: var(--JL-color-neutral-5);
        overflow: hidden;
      }

      &.is-active.is-closable .is-icon-close,
      &.is-closable:hover .is-icon-close {
        width: 14px;
        margin-left: 8px;
      }

      .is-icon-close:hover,
      .is-icon-close:active {
        background-color: transparent;
        color: var(--JL-color-neutral-7);
      }
    }

    .#{$namespace}-tabs__nav-prev,
    .#{$namespace}-tabs__nav-next {
      display: flex;
      align-items: center;
      justify-content: center;
      top: 0;
      height: $tabHeight;
      line-height: $tabHeight;
      color: var(--JL-color-neutral-5);

      .#{$namespace}-icon {
        width: 14px;
        height: 14px;
        font-size: 14px;
        line-height: 1;
      }

      &:hover,
      &:active {
        color: var(--JL-color-neutral-7);
      }
    }

    .#{$namespace}-tabs__nav-prev {
      padding-left: 12px;
    }

    &.#{$namespace}-tabs--card > {
      .#{$namespace}-tabs__header {
        border: none;
        background: transparent;

        .#{$namespace}-tabs__nav {
          border: none;
          border-bottom: none;
          border-radius: 0;

          .#{$namespace}-tabs__item {
            border-left: none;
            border-top: none;
            border-bottom: none;
            margin-top: 0;
          }
        }
      }
    }

    .#{$namespace}-tabs__item.is-active {
      color: $color-blue;
      font-weight: 500;
      position: relative;
    }
  }
}

.context-menu {
  position: absolute;
  z-index: 99999;
  box-shadow: 0 0 10px 0 rgba(#000, 0.1);
  border-radius: 2px;
  overflow: hidden;
  .menu-item {
    text-align: left;
    padding: 12px 20px;
    background: #fff;
    box-sizing: border-box;
    transition: all 0.2s;
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
    > span {
      margin-left: 5px;
    }
    &:hover {
      background: $color-blue;
      color: #fff;
    }
  }
}

.nav-bar {
  @include flexAside();
  height: $tabHeight;
  align-items: center;
  background: #fff;
  .page-tag {
    display: flex;
    .page-tag-item {
      padding: 2px 5px;
    }
  }

  :deep(.is-top) {
    margin-bottom: 0;
  }

  .demo-tabs {
    overflow: hidden;
  }
  .close-all {
    box-sizing: border-box;
    width: 44px;
    height: 100%;
    padding: 0;
    border: none;
    background: transparent;
    display: flex;
    align-items: center;
    justify-content: center;
    list-style: none;
    position: relative;
    cursor: pointer;
    color: var(--JL-color-neutral-5);

    .#{$namespace}-icon {
      font-size: 14px;
    }

    &:hover {
      color: var(--JL-color-neutral-7);
    }

    &:active {
      color: var(--JL-color-neutral-7);
    }
  }
}
</style>
