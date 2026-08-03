import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const apiProxyTarget =
  process.env.VITE_API_PROXY_TARGET || "https://192.168.20.144:8443";

export default defineConfig({
  base: "/",
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url))
    }
  },
  server: {
    host: true,
    port: 9528,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
        secure: false
      },
      "/health": {
        target: apiProxyTarget,
        changeOrigin: true,
        secure: false
      }
    }
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsDir: "static-resource/assets",
    rollupOptions: {
      output: {
        chunkFileNames: "static-resource/js/[name]-[hash].js",
        entryFileNames: "static-resource/js/[name]-[hash].js",
        assetFileNames: "static-resource/[ext]/[name]-[hash].[ext]"
      }
    }
  }
});
