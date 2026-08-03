import qs from "qs";
import request from "@/utils/request";

/**
 * @description 退出登录
 */
export function logoutReq(userCode) {
  return request({
    url: "/yjstation/api/v1/dock/auth/logout",
    method: "POST",
    data: {
      userCode: userCode
    }
  });
}

/**
 *
 * @param {*} userCode
 * @param {*} passWord
 * @returns
 */
export function LOGIN({ userCode, passWord, hospitalId }) {
  return request({
    url: "/yjstation/api/v1/dock/auth/token",
    method: "POST",
    data: {
      userCode: userCode,
      password: passWord,
      hospitalId: hospitalId
    }
  });
}

/**
 * 获取用户信息明细.
 * @param {*}
 * @returns
 */
export function getUserDetailInfo() {
  return request({
    url: `/yjstation/api/v1/dock/auth/detail`,
    method: "get"
  });
}

/**
 * 应用容器根据 token 登录接口
 */
export function PLATFORM_LOGIN(token) {
  return request({
    url: "/yjstation/api/v1/dock/auth/platform/token",
    method: "POST",
    data: {
      token
    }
  });
}

/**
 * 获取应用平台-配置应用的页面
 */
export function getAppConfigMenus(appCode) {
  return request({
    url: `/yjstation/api/v1/dock/apps/${appCode}/menus`,
    method: "GET"
  });
}

/**
 * 获取应用平台-配置应用的按钮
 */
export function getAppConfigButtons(appCode) {
  return request({
    url: `/yjstation/api/v1/dock/apps/buttons?` + qs.stringify({ appCode, current: 1, size: 9999 }),
    method: "GET"
  });
}
