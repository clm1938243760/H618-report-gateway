// import { substrPolyfill } from './tool'

export default class FormValidator {
  /**
   * 是否为手机号
   * @param {*} val
   */
  static isMobile(val) {
    return /^1[3456789]\d{9}$/.test(val);
  }

  /**
   * 是否为空
   * @param {*} val
   * @returns {boolean}
   */
  static isEmpty(val) {
    if (val === null || typeof val === "undefined" || (typeof val === "string" && val === "" && val !== "undefined")) {
      return true;
    }
    return false;
  }

  /**
   * 是否为纯英文
   * @param {*} val
   * @returns {boolean}
   */
  static isAllLatter(val) {
    return /^[a-zA-Z]+$/.test(val);
  }

  /**
   * 是否为身份证号
   * @param {String} idCard
   * @returns {Boolean}
   */
  static validateIDCard(idCard) {
    // 检查身份证号码长度
    const idCardLength = idCard.length;
    if (idCardLength !== 15 && idCardLength !== 18) {
      return false;
    }

    // 15 位身份证号码验证
    if (idCardLength === 15) {
      const pattern15 = /^[1-9]\d{5}\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}$/;
      if (!pattern15.test(idCard)) {
        return false;
      }
      const birthYear = parseInt(`19${idCard.substr(6, 2)}`, 10);
      const birthMonth = parseInt(idCard.substr(8, 2), 10);
      const birthDay = parseInt(idCard.substr(10, 2), 10);
      return isValidDate(birthYear, birthMonth, birthDay);
    }

    // 18 位身份证号码验证
    if (idCardLength === 18) {
      const pattern18 = /^[1-9]\d{5}(18|19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[0-9Xx]$/;
      if (!pattern18.test(idCard)) {
        return false;
      }
      const birthYear = parseInt(idCard.substr(6, 4), 10);
      const birthMonth = parseInt(idCard.substr(10, 2), 10);
      const birthDay = parseInt(idCard.substr(12, 2), 10);
      if (!isValidDate(birthYear, birthMonth, birthDay)) {
        return false;
      }
      const factor = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2];
      const parity = ["1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2"];
      let sum = 0;
      for (let i = 0; i < 17; i++) {
        sum += parseInt(idCard[i], 10) * factor[i];
      }
      const lastChar = idCard[17].toUpperCase();
      return lastChar === parity[sum % 11];
    }

    // 检查日期是否合法的辅助函数
    function isValidDate(year, month, day) {
      const date = new Date(year, month - 1, day);
      return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
    }
  }
}
