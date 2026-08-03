<template>
  <div class="avatar-container-user">
    <el-dropdown class="avatar-container" trigger="click">
      <span class="avatar-trigger">
        <span class="avatar-badge">
          <svg-icon name="user" :size="14"></svg-icon>
        </span>
        <span class="avatar-code">{{ displayUserCode }}</span>
      </span>

      <template #dropdown>
        <el-dropdown-menu>
          <h4 class="hospital">{{ userInfo.hospitalName }}</h4>
          <p class="desc-item">
            {{ parseUserType(userInfo.userType) }}
            <span>{{ userInfo.techuserCode ? `(${userInfo.techuserCode})` : "" }}</span>
          </p>
          <p class="desc-item">{{ userInfo.phoneNum }}</p>
          <el-dropdown-item divided :icon="SwitchButton" @click="logout">退出登录</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { SwitchButton } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { useUserStore } from "@/stores/user";
import { useDict } from "@/stores/useDict";
import { useRouter } from "vue-router";

const store = useUserStore();
const router = useRouter();
const { getDictLabel } = useDict("USER_TYPE");

const userInfo = computed(() => {
  return store.userInfo || {};
});

const displayUserCode = computed(() => {
  return userInfo.value.userName || userInfo.value.techuserName || userInfo.value.realName || userInfo.value.name || userInfo.value.userCode || userInfo.value.techuserCode || store.userCode || "";
});

const BUILTIN_USER_TYPES = {
  hospitalAdmin: "医院管理员",
  platformAdmin: "平台管理员"
};

function parseUserType(v) {
  if (BUILTIN_USER_TYPES[v]) {
    return BUILTIN_USER_TYPES[v];
  }

  return getDictLabel("USER_TYPE", v, v);
}

const logout = () => {
  store.FedLogout().then(() => {
    ElMessage.success("退出成功");
    router.replace({ name: "Login" });
  });
};
</script>

<style lang="scss" scoped>
.avatar-container-user {
  display: flex;
  align-items: center;
}

.avatar-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #fff;
  outline: none;
}

.avatar-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  color: #0097e9;
  background: #fff;
}

.avatar-code {
  max-width: 120px;
  overflow: hidden;
  font-size: 12px;
  line-height: 20px;
  color: #fff;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hospital {
  color: #333;
  line-height: 22px;
  margin: 7px;
  font-size: 14px;
}
.desc-item {
  font-size: 14px;
  color: #333;
  line-height: 22px;
  margin: 7px;
  min-width: 160px;
}
</style>
