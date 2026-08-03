<template>
  <div class="login-page">
    <img
      class="login-background"
      src="./resources/entry-bg.png"
      srcset="./resources/entry-bg.png 1x, ./resources/entry-bg@2x.png 2x"
      alt=""
    />
    <img class="login-brand" src="./resources/jl-logo.2x.png" alt="聚垒科技" />

    <section class="login-panel">
      <div class="login-heading">
        <h1>设备接入采集盒配置系统</h1>
        <p>K2B 报告上传网关</p>
      </div>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
        <el-form-item label="账号" prop="username">
          <el-input v-model="form.username" autocomplete="username" placeholder="请输入账号">
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            autocomplete="current-password"
            placeholder="请输入密码"
            show-password
            @keyup.enter="submit"
          >
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <div class="login-error" :class="{ visible: errorText }">{{ errorText || "占位" }}</div>
        <el-button class="login-submit" type="primary" :loading="loading" @click="submit">
          登录
        </el-button>
      </el-form>
      <div class="login-footer">聚垒科技 · JVLEI.COM</div>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import { Lock, User } from "@element-plus/icons-vue";
import { useRouter } from "vue-router";
import { useSessionStore } from "@/stores/session";
import { errorMessage } from "@/api/client";

const router = useRouter();
const session = useSessionStore();
const formRef = ref();
const loading = ref(false);
const errorText = ref("");
const form = reactive({
  username: "tejian01",
  password: ""
});
const rules = {
  username: [{ required: true, message: "请输入账号", trigger: "blur" }],
  password: [{ required: true, message: "请输入密码", trigger: "blur" }]
};

async function submit() {
  errorText.value = "";
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid || loading.value) return;
  loading.value = true;
  try {
    await session.login(form.username, form.password);
    router.replace("/config");
  } catch (error) {
    const backend = errorMessage(error, "登录失败");
    errorText.value =
      backend === "invalid username or password"
        ? "账号或密码错误"
        : backend === "too many failed attempts"
          ? "失败次数过多，请五分钟后再试"
          : backend;
  } finally {
    loading.value = false;
  }
}
</script>
