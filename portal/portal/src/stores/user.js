import { defineStore } from "pinia";
import { getToken, removeRefreshToken, removeToken, setToken, setRefreshToken } from "@/utils/token";
import { logoutReq, LOGIN, getUserDetailInfo, PLATFORM_LOGIN } from "@/api/user";
import { resetRouter } from "@/router/index";
import setting from "@/setting";
import { useTagStore } from "./tags";
import getMenuAndRole from "./menu";
import { clearAppMenuPermissions } from "./menu-cache";
import { checkSqlTracePermission } from "@/api/sql-trace-permission";
import { refreshAppSqlTraceAccess, resetAppSqlTraceAccess } from "@/plugins/sql-trace";

const appNameSpace = setting.appNameSpace;

export const useUserStore = defineStore({
  id: "user",
  state: () => ({
    token: getToken() || "",
    refreshToken: "",
    menus: [],
    funcs: [],
    userInfo: {}
  }),

  actions: {
    LoginEnter({ userCode, passWord, hospitalId }) {
      return new Promise((resolve, reject) => {
        LOGIN({ userCode, passWord, hospitalId })
          .then(async (res) => {
            const { code, data, msg } = res;
            if (String(code) === "500001") {
              resolve(res);
              return;
            }
            if (String(code) !== "200") throw new Error(msg);

            setToken(data.token);
            setRefreshToken(data.refreshToken);

            refreshAppSqlTraceAccess(
              { userCode },
              {
                checkPermission: checkSqlTracePermission
              }
            ).finally(() => {
              resolve(res);
            });
          })
          .catch((err) => {
            reject(err);
          });
      });
    },

    FedLogout() {
      return new Promise((resolve, reject) => {
        logoutReq(this.userCode)
          .then((res) => {
            const { code, data, msg } = res;
            if (code !== 200) throw new Error(msg);
            this.resetApp();
            resolve();
          })
          .catch((err) => {
            reject(err);
          });
      });
    },

    setUserInfo(data) {
      this.userInfo = data;
      let storageKeys = [];
      if (data) {
        storageKeys = Object.keys(data).filter((v) => !["menus"].includes(v));
      }
      localStorage.setItem(`${appNameSpace}.userInfo`, data ? JSON.stringify(data, storageKeys) : "");
    },

    setMenuList(list) {
      this.menus = list;
    },

    setBtnList(list) {
      this.funcs = list || [];
    },

    async getMenuAndBtn(userCode) {
      const saveAppCode = window.sessionStorage.getItem(`${setting.appNameSpace}.appCode`);
      const appCode = saveAppCode || setting.appCode;

      const list = await getMenuAndRole(appCode, userCode);
      const menuList = list
        .filter((item) => item.visible == "1" && (item.routeFilePath || item.compoent) && (item.routeVisitPath || item.path))
        .sort((a, b) => a.orderNum - b.orderNum);

      this.setMenuList(menuList);
    },

    async getUserInfo(id) {
      const response = await getUserDetailInfo(id);
      const { data, code } = response;

      if (!data) throw new Error("Verification failed, please Login again.");
      if (code !== 200) throw data;

      this.setUserInfo(data);
      await this.getMenuAndBtn(data.userCode || id);
      return data;
    },

    clearStore() {
      this.setMenuList([]);
      this.setUserInfo({});
      this.setBtnList([]);
      clearAppMenuPermissions();
      localStorage.removeItem(`${appNameSpace}.hospitalId`);
      this.$patch((state) => {
        state.refreshToken = "";
      });
    },

    resetApp() {
      useTagStore().DELETE_ALL();
      removeToken();
      removeRefreshToken();
      resetRouter();
      resetAppSqlTraceAccess();
      this.clearStore();
    }
  }
});

export async function loginAppByPlatformToken(platformToken) {
  return new Promise((resolve, reject) => {
    PLATFORM_LOGIN(platformToken)
      .then((res) => {
        const { code, data } = res;
        if (code !== 200) {
          setToken("");
          setRefreshToken("");
          reject(res);
        } else {
          const { token, refreshToken } = data;
          setToken(token);
          setRefreshToken(refreshToken);
          resolve();
        }
      })
      .catch(reject);
  });
}
