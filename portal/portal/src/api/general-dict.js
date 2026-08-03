// api/dict.js
import request from "@/utils/request"; // 项目通用请求工具（如axios封装）

/**
 * 单个字典key的请求接口
 * @param {string} dictKey - 字典唯一标识（如："user_status"、"device_type"）
 * @returns {Promise<Array>} 字典数组（格式：[{ dictValue: "1", dictLabel: "启用" }, { dictValue: "0", dictLabel: "禁用" }]）
 */
export const getDictByKey = async (dictKey) => {
  try {
    const res = await request({
      url: "/yjstation/api/v1/base/dict/item/all", // 后端单个字典查询接口
      method: "post",
      data: { dictCode: dictKey } // 传参：单个字典key
    });

    // 适配后端响应格式（根据实际情况调整）
    // 假设后端返回：{ code: 200, data: { records: [...] } }
    if (res.code === 200 && Array.isArray(res.data)) {
      let list = res.data || []; // 最终返回字典数组
      list.forEach((item) => {
        const valType = item.dictValueType || "string";
        if (valType === "string") {
          item.dictValue = item.dictValue == void 0 ? "" : item.dictValue + "";
        } else if (valType === "number") {
          item.dictValue = [undefined, null, ""].includes(item.dictValue) ? null : Number(item.dictValue);
        }
      });
      list = list.filter((i) => i.isEnabled == 1);
      return list; // 最终返回字典数组
    }

    // 异常情况返回空数组（避免组件报错）
    console.warn(`字典${dictKey}请求返回格式异常`, res);
    return [];
  } catch (error) {
    console.log("error", error);
    console.error(`字典${dictKey}请求失败`, error);
    return [];
  }
};
