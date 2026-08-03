import { defineStore } from "pinia";
import { Storage } from "@/utils/storage";
import setting from "@/setting";
import eventEmitter from "@/utils/eventEmitter";
import { convertToCamelCase, findNodeInTree } from "@/utils/tool";
// import router from '@/router'

const appNameSpace = setting.appNameSpace;
// visitedRoutes本地缓存
const getCacheVisitedRoutes = () => {
  const visitedRoutes = Storage.get(`${appNameSpace}.visitedRoutes`);
  return visitedRoutes || [];
};
const setCacheVisitedRoutes = (visitedRoutes) => {
  Storage.set(`${appNameSpace}.visitedRoutes`, visitedRoutes);
};
const getCacheVisitedRouteHistory = () => {
  const visitedRouteHistory = Storage.get(`${appNameSpace}.visitedRouteHistory`);
  return visitedRouteHistory || [];
};
const setCacheVisitedRouteHistory = (visitedRouteHistory) => {
  Storage.set(`${appNameSpace}.visitedRouteHistory`, visitedRouteHistory);
};

// 解析并拼接基础路径和路由路径，生成菜单链接
function resolvePath(basePath, routePath) {
  if (basePath.endsWith("/")) return `${basePath}${routePath.startsWith("/") ? routePath.slice(1) : routePath}`;
  return `${basePath}/${routePath.startsWith("/") ? routePath.slice(1) : routePath}`;
}

// 根据全路径, 匹配对应声明的路由
const findMatchRouteByFullPath = (fullPath, routes) => {
  const node = findNodeInTree(
    routes,
    (node, pNode, level) => {
      const { path } = node;
      if (path === fullPath) {
        return true;
      }

      const combPath = resolvePath(pNode?.path || "", path);
      return fullPath === combPath;
    },
    "children"
  );

  return node;
};

// 获取路由的名称: 如果是只有一个子路由, 名称取子路由的名称
function getRouteName(curRoute) {
  let routeName = curRoute.meta?.title;
  if (!routeName && curRoute.children && curRoute.children.length) {
    routeName = curRoute.children[0].meta?.title;
  }
  return routeName;
}

export const useTagStore = defineStore({
  id: "tag",
  state: () => ({
    visitedRoutes: [],
    visitedRouteHistory: getCacheVisitedRouteHistory(),
    viewIndex: -1
  }),

  actions: {
    // 选择视图
    SELECT_VIEW(index) {
      this.viewIndex = index;
    },
    RECORD_VISITED_ROUTE(path) {
      if (!path) {
        return;
      }

      const context = this;
      context.visitedRouteHistory = context.visitedRouteHistory.filter((item) => item !== path);
      context.visitedRouteHistory.push(path);
      setCacheVisitedRouteHistory(context.visitedRouteHistory);
    },
    // 切换视图
    SWITCH_VIEW(path) {
      const context = this;
      const targetIndex = context.visitedRoutes.findIndex((item) => item.path === path);
      if (targetIndex !== -1) {
        context.SELECT_VIEW(targetIndex);
      } else {
        context.SELECT_VIEW(context.visitedRoutes.length - 1);
      }
    },
    // 添加
    ADD_VISITED_ROUTE(route /* { path: 页签路径, name: 页签标题, ... } */, routes) {
      const context = this;
      const targetIndex = context.visitedRoutes.findIndex((item) => item.path === route.path);

      if (!route.name && routes) {
        const page = findMatchRouteByFullPath(route.path, routes);
        if (page) {
          const name = getRouteName(page);
          if (name) {
            route.name = name;
          }
        }
      }

      if (!route.key) {
        route.key = convertToCamelCase(route.path);
      }

      if (targetIndex !== -1) {
        Object.assign(context.visitedRoutes[targetIndex], route);
        setCacheVisitedRoutes(context.visitedRoutes);
        context.SELECT_VIEW(targetIndex);
        context.RECORD_VISITED_ROUTE(route.path);
        return;
      }

      context.visitedRoutes.push(route);
      setCacheVisitedRoutes(context.visitedRoutes);
      context.SELECT_VIEW(context.visitedRoutes.length - 1);
      context.RECORD_VISITED_ROUTE(route.path);
    },
    // 删除
    DELETE_VISITED_ROUTE(route) {
      const context = this;
      let toDeleteIdx = -1;
      let toDeleteRoute = null;
      const oldViewPath = context.visitedRoutes[context.viewIndex]?.path;

      if (typeof route === "object" && route) {
        const matchIdx = context.visitedRoutes.findIndex((item) => item.path === route.path);
        if (matchIdx !== -1) {
          toDeleteIdx = matchIdx;

          toDeleteRoute = context.visitedRoutes.splice(matchIdx, 1);
        }
      } else if (typeof route === "number" && route > -1 && route < context.visitedRoutes.length) {
        toDeleteIdx = route;
        toDeleteRoute = context.visitedRoutes.splice(toDeleteIdx, 1);
      }

      setCacheVisitedRoutes(context.visitedRoutes);
      context.visitedRouteHistory = context.visitedRouteHistory.filter((item) => item !== toDeleteRoute?.[0]?.path);
      setCacheVisitedRouteHistory(context.visitedRouteHistory);

      if (oldViewPath && oldViewPath !== toDeleteRoute?.[0]?.path) {
        const currentIndex = context.visitedRoutes.findIndex((item) => item.path === oldViewPath);
        context.SELECT_VIEW(currentIndex);
        eventEmitter.emit("tag.close", toDeleteRoute);
        return context.visitedRoutes[currentIndex];
      }

      const fallbackPath = [...context.visitedRouteHistory].reverse().find((path) => context.visitedRoutes.some((item) => item.path === path));
      if (fallbackPath) {
        const fallbackIndex = context.visitedRoutes.findIndex((item) => item.path === fallbackPath);
        context.SELECT_VIEW(fallbackIndex);
        eventEmitter.emit("tag.close", toDeleteRoute);
        return context.visitedRoutes[fallbackIndex];
      }

      if (context.visitedRoutes[toDeleteIdx]) {
        context.SELECT_VIEW(toDeleteIdx);
      } else if (context.visitedRoutes[toDeleteIdx - 1]) {
        context.SELECT_VIEW(toDeleteIdx - 1);
      } else {
        context.SELECT_VIEW(-1);
      }

      eventEmitter.emit("tag.close", toDeleteRoute);
      return context.visitedRoutes[context.viewIndex];
    },
    // 删除除了本身以外的
    DELETE_OTHERS_VISITED_ROUTE(route) {
      const context = this;
      context.visitedRoutes = context.visitedRoutes.filter((item) => item.path === route.path);
      context.visitedRouteHistory = context.visitedRouteHistory.filter((item) => item === route.path);
      setCacheVisitedRoutes(context.visitedRoutes);
      setCacheVisitedRouteHistory(context.visitedRouteHistory);
      context.SELECT_VIEW(0);
    },
    DELETE_ALL() {
      const context = this;
      context.visitedRoutes = [];
      context.visitedRouteHistory = [];
      setCacheVisitedRoutes([]);
      setCacheVisitedRouteHistory([]);
      context.SELECT_VIEW(-1);

      eventEmitter.emit("tag.closeAll");
    },
    // 更新当前
    UPDATE_VISITED_ROUTE(route) {
      const context = this;
      context.visitedRoutes.forEach((item) => {
        if (item.path === route.path) {
          Object.assign(item, route);
        }
      });
    }
  }
});
