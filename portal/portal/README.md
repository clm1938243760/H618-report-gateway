# 安装

node 20.18.1

推荐使用 yarn, 安装更快

运行 yarn run dev

发布 yarn run build

# 组件

组件参考 http://jlcomponents.ad.juleitech.com/ 私有库组件 包含列表、上传组件、布局组件等

一般的CRUD页面
搜索框放在el-form里面 然后使用el-row和el-col gutter=24 col=6 一行放4个

详情、新增、编辑页面最好通过弹框(el-dialog)或者内嵌v-if的方式切换展示

# 配置修改、菜单列表

在src/settings.js当中有appCode这个字段对应了门户里面的appCode，需要匹配上才能从应用当中找到菜单
