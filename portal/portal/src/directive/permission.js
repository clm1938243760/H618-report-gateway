import { useUserStore } from "@/stores/user";

/**
 * v-permission: 权限控制指令
 * 接收参数：数组或字符串。如果是字符串, 会依据 , 号解析为数组, 然后对判断数组中的所有项, 只要有任意一项符合, 则通过（暂不处理 与或 关系）
 * 数组元素为以下几种表示:
 *  1. * 不限制, 全部开放
 *  2. (按菜单) m:菜单ID, 针对拥有某些菜单的用户开放, 多个菜单用 +或/ 拼接
 *  3. (按角色) r:角色名称 针对某类角色的用户开放, 多个角色用 +或/ 拼接
 *  4. (按用户) i:用户ID 针对某个特定的用户开放, 多个用户用 +或/ 拼接
 *  5. (按功能) f:功能ID 针对某些功能开放, 多个功能用 +或/ 拼接
 */
function checkPermission(el, binding) {
  let { value } = binding;

  const userStore = useUserStore();
  const menus = userStore.menus || [];
  const userId = String(userStore.userInfo?.id ?? userStore.userId ?? "");
  const userType = userStore.userInfo?.userType ?? userStore.userType;
  const menusId = menus.map((v) => v.id);
  const userFuncs = userStore.funcs || [];

  if (value) {
    let publicRoleOrMenuIds = [];
    if (Array.isArray(value)) {
      publicRoleOrMenuIds = value;
    } else {
      value = String(value);
      publicRoleOrMenuIds = value.split(",");
    }

    const hasMatchOne = publicRoleOrMenuIds.some((roleOrMenuId) => {
      roleOrMenuId += "";
      // 开放所有
      if (roleOrMenuId === "*") {
        return true;
      }
      // 对指定的菜单开放（ID 为字符串，不做类型转换）
      if (roleOrMenuId.startsWith("m:")) {
        const toOpenMenus = roleOrMenuId.slice(2).split(/[+/]/);
        return toOpenMenus.some((menuId) => menusId.includes(menuId));
      }
      // 对指定的角色开放
      if (roleOrMenuId.startsWith("r:")) {
        const toOpenRoles = roleOrMenuId.slice(2).split(/[+/]/);

        return toOpenRoles.some((role) => role === userType);
      }
      // 对指定的人员开放
      if (roleOrMenuId.startsWith("i:")) {
        const toOpenIds = roleOrMenuId.slice(2).split(/[+/]/);

        return toOpenIds.some((id) => id === userId);
      }
      // 对指定的功能开放
      if (roleOrMenuId.startsWith("f:")) {
        const toOpenFuncs = roleOrMenuId.slice(2).split(/[+/]/);

        return toOpenFuncs.some((func) => userFuncs.includes(func));
      }
      return false;
    });

    if (!hasMatchOne) {
      el.parentNode && el.parentNode.removeChild(el);
    }
  } else {
    // throw new Error(`需要设置具体的值! 例如 v-permission="['nurse']"`)
    console.error('需要设置具体的值! 例如 v-permission=["nurse"]');
  }
}

// vue2和vue3中指令对比https://jishuin.proginn.com/p/763bfbd29cb7
export default {
  mounted(el, binding) {
    checkPermission(el, binding);
  },
  componentUpdated(el, binding) {
    checkPermission(el, binding);
  }
};
