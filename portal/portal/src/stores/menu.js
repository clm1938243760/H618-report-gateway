import { ElMessage } from "element-plus";
import request from "@/utils/request.js";
import setting from "@/setting.js";
import { useUserStore } from "@/stores/user";
import { getAppMenuPermissions, setAppMenuPermissions } from "@/stores/menu-cache";

let appCode = "";

/**
 * 获取菜单和按钮权限入口
 */
const getMenuAndRole = (code, userCode) => {
  appCode = code;
  getAppTitle();
  return getMenusAndButtonsFromPortal(userCode);
};

/**
 * 获取应用标题
 */
const getAppTitle = () => {
  request({ url: "/yjstation/api/v1/dock/apps/list", method: "get" }).then((res) => {
    if (res.code == 200) {
      const appItem = (res.data || []).find((i) => i.code == appCode);
      if (appItem) {
        setting.title = appItem.name;
        document.title = appItem.name;
      }
    }
  });
};

/**
 * 从门户接口获取菜单和按钮权限
 * 接口：/yjstation/api/v1/dock/panel/user/apps/{appCode}/permissions
 */
const getMenusAndButtonsFromPortal = (userCode) => {
  const savedAppCode = window.sessionStorage.getItem(`${setting.appNameSpace}.appCode`);
  const actualAppCode = savedAppCode || appCode;
  const userStore = useUserStore();
  const cachedPermissions = getAppMenuPermissions({ appCode: actualAppCode, userCode });

  if (cachedPermissions) {
    userStore.setBtnList(cachedPermissions.buttons);
    return Promise.resolve(cachedPermissions.menus);
  }

  return new Promise((resolve, reject) => {
    request({
      url: `/yjstation/api/v1/dock/panel/user/apps/${actualAppCode}/permissions`,
      method: "get"
    })
      .then((res) => {
        if (res.code === 200) {
          const data = res.data || {};

          // 过滤掉应用根菜单（isAppRoot === 1）
          const menuList = (data.menus || []).filter((menu) => menu.isAppRoot !== 1);

          // 启用的按钮权限码列表
          const funcCodes = (data.buttons || [])
            .filter((btn) => btn.isEnabled === 1 && btn.buttonCode)
            .map((btn) => btn.buttonCode);

          // 存入 Pinia，供 v-permission 指令使用
          userStore.setBtnList(funcCodes);
          setAppMenuPermissions({
            appCode: actualAppCode,
            userCode,
            menus: menuList,
            buttons: funcCodes
          });

          resolve(menuList);
        } else {
          ElMessage.error(res.msg || "获取菜单失败");
          resolve([]);
        }
      })
      .catch((err) => {
        console.error("获取菜单权限失败:", err);
        reject(err);
      });
  });
};

export default getMenuAndRole;
