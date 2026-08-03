<template>
  <div class="layout-error">
    <div class="inner-box">
      <p>
        <span class="el-icon-lock icon"></span>
        <span class="text">您没有访问该内容的权限</span>

        <el-link type="primary" @click="onBack">返回上一页</el-link>
      </p>
    </div>
  </div>
</template>

<script>
export default {
  methods: {
    onBack() {
      this.$router.back();
    }
  }
};
</script>

<style lang="scss" scoped>
.layout-error {
  img {
    width: 800px;
  }
  display: flex;
  justify-content: center;
  height: 100%;
  .inner-box {
    margin-top: 20%;
    p {
      margin: 15px auto;
      display: flex;
      align-items: center;
      .icon {
        margin-top: 3px;
        margin-right: 3px;
      }
      .text {
        margin-right: 8px;
      }
    }
  }
}
</style>
