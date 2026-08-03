<template>
  <div class="navbar">
    <AvatarImg />

    <slot name="default"></slot>
    <slot name="message"></slot>
    <AvatarIcon class="avatar-container" />
  </div>
</template>

<script setup>
import AvatarImg from "./AvatarImg.vue";
import AvatarIcon from "./AvatarIcon.vue";
</script>

<style lang="scss" scoped>
.navbar {
  z-index: 9;
  position: relative;
  display: flex;
  align-items: center;
  width: 100%;
  height: $appHeaderHeight;
  padding: 0 24px;
  overflow: hidden;
  background: var(--JL-color-primary);
  color: #fff;
  box-sizing: border-box;
  &.shadow {
    box-shadow: 0 4px 4px rgba(0, 21, 41, 0.08);
    -webkit-box-shadow: 0 4px 4px rgba(0, 21, 41, 0.08);
  }

  .language-container {
    margin-left: auto;
  }

  .avatar-container {
    margin-left: auto;
    cursor: pointer;
  }
}
</style>
