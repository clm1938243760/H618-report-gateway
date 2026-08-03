/* eslint-env node */
require("@rushstack/eslint-patch/modern-module-resolution");

module.exports = {
  root: true,
  env: {
    node: true,
    es6: true,
    browser: true
  },
  extends: ["plugin:vue/vue3-essential", "eslint:recommended", "@vue/eslint-config-prettier/skip-formatting"],
  parserOptions: {
    ecmaVersion: "latest"
  },
  rules: {
    "no-console": process.env.NODE_ENV === "production" ? "warn" : "off",
    "no-debugger": process.env.NODE_ENV === "production" ? "warn" : "off",
    // 禁止出现未使用过的变量
    "no-unused-vars": "off",
    // 多个单词命名组件
    "vue/multi-word-component-names": "off",
    // 要求回调函数中有容错处理
    "handle-callback-err": "error",
    // 禁止出现空语句块
    "no-empty": "off",
    // 强制一行的最大长度
    "max-len": "off",
    // 禁止使用__proto__属性
    "no-proto": 2,
    // 禁止多次声明同一变量
    "no-redeclare": 2,
    // 禁用with语句
    "no-with": 2,
    // 强制 getter 和 setter在对象中成对出现
    "accessor-pairs": 2,
    // 末尾分号
    semi: ["error", "always"],
    // 末尾逗号
    "comma-dangle": [2, "never"],
    // 需要使用 === 和 !==
    eqeqeq: "off"
  }
};
