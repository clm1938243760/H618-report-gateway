// hooks/useDict.js
import { computed, onUnmounted } from "vue";
import { useDictStore } from "@/stores/dict";

/**
 * 组件级字典调用Hook（极简API）
 * @param {string|Array<string>} dictKeys - 单个字典key或多个key数组
 * @returns {Object} { 字典key: 字典数组, getDictLabel: 通用标签转换函数 }
 *
 * 示例1：单个字典 → useDict("user_status") → { user_status: [...], getDictLabel }
 * 示例2：多个字典 → useDict(["user_status", "device_type"]) → { user_status: [...], device_type: [...], getDictLabel }
 */
export const useDict = (dictKeys) => {
  const dictStore = useDictStore();
  const keys = Array.isArray(dictKeys) ? dictKeys : [dictKeys];

  // 1. 初始化：提前请求字典（确保组件渲染时数据已准备）
  const initDict = async () => {
    await Promise.all(keys.map((key) => dictStore.getDict(key)));
  };
  initDict(); // 组件加载时自动请求

  // 2. 构建字典响应式数据（computed确保自动更新）
  const dictResult = {};
  keys.forEach((key) => {
    dictResult[key] = computed(() => dictStore.dictMap[key] || []);
  });

  // 3. 通用字典标签转换函数（根据code获取label，支持默认值）
  /**
   * @param {string} dictKey - 字典标识
   * @param {string|number} code - 字典编码
   * @param {string} defaultLabel - 未匹配时的默认值（默认：""）
   * @returns {string} 字典标签
   */
  dictResult.getDictLabel = (dictKey, value, defaultLabel = "") => {
    const dictList = dictStore.dictMap[dictKey] || [];
    const item = dictList.find((item) => item.dictValue === value);

    return item ? item.dictLabel : defaultLabel;
  };

  // 4. 可选：组件卸载时清除未使用的字典缓存（根据需求决定是否开启）
  // onUnmounted(() => {
  //   keys.forEach(key => {
  //     // 可根据“字典是否被其他组件使用”决定是否清除（需额外实现使用计数）
  //     // 简单场景：不清除，依赖Pinia持久化或全局缓存
  //   });
  // });

  return dictResult;
};
