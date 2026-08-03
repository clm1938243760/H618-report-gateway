// store/modules/dictStore.js
import { defineStore } from "pinia";
import { getDictByKey } from "@/api/general-dict";
import setting from "@/setting";

// 定义字典Store
export const useDictStore = defineStore("dict", {
  state: () => ({
    // 字典缓存：key=字典标识，value=字典数组（如：{ "user_status": [{ code: "1", label: "启用" }] }）
    dictMap: {},
    // 请求状态：避免同一字典重复请求（key=字典标识，value=Promise）
    requestCache: {}
  }),

  actions: {
    /**
     * 1. 获取字典（核心方法）
     * - 优先从缓存取，无缓存则请求，同一key避免重复请求
     * @param {string} dictKey - 字典标识
     * @returns {Promise<Array>} 字典数组
     */
    async getDict(dictKey) {
      // 1. 缓存存在：直接返回
      // if (this.dictMap[dictKey]) {
      //   return Promise.resolve(this.dictMap[dictKey]);
      // }

      // 2. 正在请求中：返回同一Promise（避免重复请求）
      if (this.requestCache[dictKey]) {
        return this.requestCache[dictKey];
      }

      // 3. 发起请求：缓存Promise，避免并发重复请求
      this.requestCache[dictKey] = getDictByKey(dictKey)
        .then((dictList) => {
          // 请求成功：更新字典缓存
          this.dictMap[dictKey] = dictList;
          return dictList;
        })
        .finally(() => {
          // 请求结束：清除请求缓存
          delete this.requestCache[dictKey];
        });

      return this.requestCache[dictKey];
    },

    /**
     * 2. 主动更新字典（支持单个/多个key）
     * - 用于字典数据变更后（如新增/编辑字典），主动刷新全局缓存
     * @param {string|Array<string>} dictKeys - 单个字典key或多个key数组
     */
    async refreshDict(dictKeys) {
      const keys = Array.isArray(dictKeys) ? dictKeys : [dictKeys];

      // 批量更新：逐个请求并更新缓存
      await Promise.all(
        keys.map(async (key) => {
          const newDictList = await getDictByKey(key);
          this.dictMap[key] = newDictList; // 直接覆盖旧缓存
        })
      );
    },

    /**
     * 3. 清空指定字典缓存（可选）
     * @param {string} dictKey - 字典标识
     */
    clearDict(dictKey) {
      delete this.dictMap[dictKey];
    },

    /**
     * 4. 清空所有字典缓存（如用户退出登录时）
     */
    clearAllDict() {
      this.dictMap = {};
      this.requestCache = {};
    }
  }
});
