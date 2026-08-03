# 宿主与子应用路由同步

本文说明宿主应用和子应用之间的路由同步协议。当前模板保留 `micro-app`、`wujie`、`qiankun` 和独立运行兼容，其中主子路由双向同步只在 `micro-app` 运行时启用。

## 核心概念

`subPath` 是宿主传给子应用的内部路由路径，表示宿主希望子应用打开哪个页面。它不是完整 URL，也不是宿主容器路由。

示例：

```js
{
  appCode: "app-template",
  subPath: "/el/template-standard-list"
}
```

子应用内部真实路由可能带应用前缀或平台菜单前缀：

```text
/el/template-standard-list
```

因此同步逻辑同时兼容带前缀和不带前缀的 `subPath`。

当前模板配置：

```js
{
  appName: "el",
  inboundRoutePrefixes: ["el"],
  outboundRoutePrefix: ""
}
```

`inboundRoutePrefixes` 用于宿主到子应用方向，表示宿主传入 `subPath` 时可兼容的路径前缀。`outboundRoutePrefix` 用于子应用到宿主方向，表示回写宿主时需要补齐的菜单路径前缀。模板的宿主路径和内部路由都带 `/el`，所以 `outboundRoutePrefix` 为空。

## 文件职责

- `src/micro-app/runtime.js`
  - 识别当前运行环境：`micro-app`、`wujie`、`qiankun`、`standalone`
  - 创建并应用 `hostContext`
  - 读取宿主初始 `subPath`
  - 监听宿主后续 `subPath` 变化
  - 在 `micro-app` 下向宿主回传子应用路由变化

- `src/micro-app/route-sync.js`
  - 连接运行时适配层和纯路由同步逻辑
  - 将 `getInitialSubPath` 和 `onSubPathChange` 注入 `route-sync-core`

- `src/micro-app/route-sync-core.js`
  - 处理纯路由同步逻辑
  - 等待动态权限路由 ready
  - 暂存动态路由 ready 前收到的 `subPath`
  - 解析宿主 `subPath` 到子应用真实 Vue Router 路由
  - 将子应用真实路由转换回宿主使用的 `subPath`

- `src/App.vue`
  - 登录后加载动态权限路由
  - 动态路由完成后调用 `routeSync.markReady()`

- `src/router/index.js`
  - 在路由跳转完成后调用 `emitRouteChange(to)`，通知宿主当前子应用路由

## 宿主到子应用

宿主通过 `micro-app` data 向子应用传递 `subPath`。

初始加载时，子应用从 `window.microApp.getData()` 读取：

```js
{
  token: "...",
  freshToken: "...",
  userCode: "...",
  appCode: "app-template",
  subPath: "/el/template-standard-list"
}
```

运行过程中，宿主通过更新 data 切换子应用页面：

```js
microApp.setData("app-template", {
  subPath: "/el/template-standard-list"
});
```

子应用通过 `window.microApp.addDataListener` 接收后续变化。

## 同步时序

子应用启动时，静态路由已经存在，但权限菜单对应的动态路由还没有注册。因此子应用不能在收到 `subPath` 后立刻跳转。

同步时序如下：

```text
子应用启动
  ↓
读取宿主 hostContext
  ↓
启动 routeSync.start()
  ↓
监听宿主 subPath
  ↓
登录并获取用户信息
  ↓
根据权限注册动态路由
  ↓
调用 routeSync.markReady()
  ↓
把宿主 subPath 同步到 Vue Router
```

如果动态路由 ready 前已经收到宿主 `subPath`，子应用会先暂存，等 `markReady()` 后再跳转。

## 路由匹配规则

宿主传入的 `subPath` 会先被标准化：

```text
""                         -> "/"
"template-standard-list"   -> "/template-standard-list"
"/template-standard-list"  -> "/template-standard-list"
```

当 `appName = "el"` 时：

宿主传不带应用前缀：

```text
/template-standard-list
```

子应用会尝试匹配：

```text
/template-standard-list
/el/template-standard-list
```

宿主传带应用前缀：

```text
/el/template-standard-list
```

子应用会尝试匹配：

```text
/el/template-standard-list
/template-standard-list
```

这样做是为了兼容两类菜单配置：

- 宿主菜单只保存子应用内部路径
- 宿主菜单保存包含应用名前缀的完整子应用路径

## 动态路由未就绪

动态路由未就绪时：

```js
routeSync.sync("/template-standard-list")
```

不会立即执行 `router.replace()`，而是暂存：

```text
pendingSubPath = "/template-standard-list"
```

动态路由完成后：

```js
routeSync.markReady()
```

会优先使用 `pendingSubPath`，而不是启动时的初始 `subPath`。原因是 pending 值代表宿主后续推送的更新，比初始快照更新。

## 子应用到宿主

子应用内部路由变化后，会在 `router.afterEach` 中通知宿主：

```js
emitRouteChange(to);
```

在 `micro-app` 运行时，发送的数据格式为：

```js
{
  type: "route-change",
  appCode: "app-template",
  subPath: "/el/template-standard-list",
  title: "普通列表模板"
}
```

宿主可以用这个事件同步：

- 当前菜单高亮
- 标签页
- 浏览器地址
- 面包屑或页面标题

## 边界规则

- `subPath === "/"` 表示没有明确目标子路由，当前逻辑不会强制跳转。
- 路由匹配会忽略 `pre-loading`、`every-to-not-found`、`404`、`401` 这类兜底路由。
- 非 `micro-app` 运行时，`getInitialSubPath()` 返回 `/`，`onSubPathChange()` 返回空取消函数。
- 当前只在 `micro-app` 下回传 `route-change`，`qiankun` 和 `wujie` 保持原行为。
- 子应用启动页、登录页、404/401 和兜底路由不会回传给宿主，避免刷新深链时被启动过程覆盖。

## 常见问题

### 为什么不直接在收到 subPath 时跳转？

因为子应用菜单路由来自用户权限，必须等登录和 `addDynamicRoutesByRole()` 完成后才存在。提前跳转可能命中兜底路由，或者出现 Vue Router no match 警告。

### 为什么要区分 inboundRoutePrefixes 和 outboundRoutePrefix？

`inboundRoutePrefixes` 解决宿主传入路径如何匹配子应用真实路由。`outboundRoutePrefix` 解决子应用真实路由如何回写成宿主菜单路径。

模板的宿主菜单路径和内部真实路由都是 `/el/template-standard-list`，所以只需要入站识别 `/el`，出站不需要额外补前缀。

### 为什么同时匹配带前缀和不带前缀？

宿主菜单和子应用路由的路径约定可能不一致。同步逻辑同时尝试两种形态，可以避免要求所有宿主菜单立即统一改造。

### 为什么 route-sync-core 不直接依赖 runtime？

`runtime.js` 依赖浏览器和微前端环境，例如 `window.microApp`、`vite-plugin-qiankun`。`route-sync-core.js` 只保留纯路由算法，方便用 Node 直接测试，并避免单测加载浏览器运行时依赖。
