<template>
  <div class="page-shell network-page" v-loading="loading">
    <div class="page-heading">
      <div>
        <h1>网络配置</h1>
        <p>查看有线网络、连接 Wi-Fi，并配置本机维护热点。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" @click="loadNetwork(true)">刷新状态</el-button>
        <el-button
          type="primary"
          :icon="Search"
          :loading="scanning"
          :disabled="!wifi.radio_enabled"
          @click="scanNetworks"
        >
          扫描附近网络
        </el-button>
      </div>
    </div>

    <section class="surface network-section wired-section">
      <div class="surface-heading network-section-heading">
        <div>
          <h2>有线网络</h2>
          <span class="section-note">设备接入网口状态</span>
        </div>
        <el-tag :type="wired.connected ? 'success' : 'info'" effect="light">
          {{ wired.connected ? "已连接" : "未连接" }}
        </el-tag>
      </div>
      <div class="network-status-row">
        <div><span>网卡</span><strong>{{ wired.device || "-" }}</strong></div>
        <div><span>有线 IP</span><strong>{{ wiredIp || "-" }}</strong></div>
        <div><span>MAC 地址</span><strong>{{ wired.mac || "-" }}</strong></div>
        <div><span>默认网关</span><strong>{{ wired.gateway || "-" }}</strong></div>
        <div><span>接口状态</span><strong>{{ wired.connected ? "链路正常" : "网线未连接" }}</strong></div>
      </div>
    </section>

    <section class="surface network-section wifi-section">
      <div class="surface-heading network-section-heading">
        <div>
          <h2>Wi-Fi 网络</h2>
          <span class="section-note">有线可用时保持有线网络优先</span>
        </div>
        <el-switch
          v-model="radioEnabled"
          inline-prompt
          active-text="开启"
          inactive-text="关闭"
          :loading="radioLoading"
          :disabled="!wifi.available"
          @change="setRadio"
        />
      </div>

      <el-alert
        v-if="!wifi.available"
        :title="wifi.error || '未检测到可用的 Wi-Fi 设备'"
        type="error"
        :closable="false"
        show-icon
        class="page-alert"
      />

      <div class="wifi-current-strip">
        <div><span>当前网络</span><strong>{{ wifi.connected ? wifi.ssid || wifi.connection : "未连接" }}</strong></div>
        <div><span>Wi-Fi IP</span><strong>{{ wifiIp || "-" }}</strong></div>
        <div><span>信号</span><strong>{{ wifi.connected ? `${wifi.signal}%` : "-" }}</strong></div>
        <div><span>安全类型</span><strong>{{ wifi.security || "-" }}</strong></div>
      </div>

      <el-form ref="formRef" :model="wifiForm" label-position="top" class="network-form">
        <div class="network-form-grid wifi-form-grid">
          <el-form-item label="无线网卡" prop="device" :rules="requiredRules('请选择无线网卡')">
            <el-select v-model="wifiForm.device" :disabled="connecting">
              <el-option
                v-for="item in wifiClientDevices"
                :key="item.device"
                :label="deviceLabel(item)"
                :value="item.device"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="Wi-Fi 名称（SSID）" prop="ssid" :rules="requiredRules('请选择或输入 Wi-Fi 名称')">
            <el-select
              v-model="wifiForm.ssid"
              filterable
              allow-create
              default-first-option
              placeholder="选择附近网络或直接输入"
              :disabled="connecting || !wifi.radio_enabled"
            >
              <el-option v-for="item in networks" :key="item.ssid" :label="networkLabel(item)" :value="item.ssid" />
            </el-select>
          </el-form-item>
          <el-form-item label="Wi-Fi 密码">
            <el-input
              v-model="wifiForm.password"
              type="password"
              show-password
              maxlength="64"
              autocomplete="new-password"
              placeholder="开放网络可不填写"
              :disabled="connecting"
              @keyup.enter="connectWifi"
            />
          </el-form-item>
          <el-form-item label="连接选项" class="compact-switches">
            <el-checkbox v-model="wifiForm.autoconnect">开机自动连接</el-checkbox>
            <el-checkbox v-model="wifiForm.hidden">隐藏网络</el-checkbox>
          </el-form-item>
        </div>
        <div class="connection-actions compact-actions">
          <el-button type="primary" :icon="Link" :loading="connecting" :disabled="!wifi.radio_enabled" @click="connectWifi">
            连接 Wi-Fi
          </el-button>
          <el-button v-if="wifi.connected" :icon="SwitchButton" :loading="disconnecting" @click="disconnectWifi">
            断开连接
          </el-button>
          <el-button v-if="wifi.connected" type="danger" plain :icon="Delete" :loading="forgetting" @click="forgetWifi">
            断开并忘记
          </el-button>
        </div>
      </el-form>

      <div class="nearby-heading">
        <h3>附近网络</h3>
        <span>{{ networks.length ? `发现 ${networks.length} 个网络` : "尚未扫描" }}</span>
      </div>
      <el-table :data="networks" stripe height="205" highlight-current-row size="small" @row-click="selectNetwork">
        <el-table-column label="Wi-Fi 名称" min-width="280">
          <template #default="{ row }">
            <span class="wifi-network-name">
              <el-tag v-if="row.active" type="success" effect="light" size="small">当前</el-tag>
              {{ row.ssid }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="信号" width="190">
          <template #default="{ row }">
            <div class="wifi-signal compact-signal">
              <el-progress :percentage="row.signal" :stroke-width="6" :show-text="false" />
              <span>{{ row.signal }}%</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="频段" width="100">
          <template #default="{ row }">{{ row.frequency >= 5000 ? "5 GHz" : "2.4 GHz" }}</template>
        </el-table-column>
        <el-table-column prop="security" label="安全类型" min-width="170" />
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ row }"><el-button link type="primary" @click.stop="selectNetwork(row)">选择</el-button></template>
        </el-table-column>
        <template #empty><el-empty description="没有扫描结果" :image-size="58" /></template>
      </el-table>
    </section>

    <section class="surface network-section hotspot-section">
      <div class="surface-heading network-section-heading">
        <div>
          <h2>维护热点</h2>
          <span class="section-note">手机或笔记本可连接热点访问本机管理页面</span>
        </div>
        <div class="hotspot-heading-actions">
          <span class="hotspot-clients">已连接 {{ hotspot.clients || 0 }} 台</span>
          <el-switch
            v-model="hotspotEnabled"
            inline-prompt
            active-text="开启"
            inactive-text="关闭"
            :loading="hotspotSwitching"
            :disabled="!hotspot.available"
            @change="switchHotspot"
          />
        </div>
      </div>

      <el-form ref="hotspotFormRef" :model="hotspotForm" label-position="top" class="network-form">
        <div class="network-form-grid hotspot-form-grid">
          <el-form-item label="热点名称（SSID）" prop="ssid" :rules="requiredRules('请输入热点名称')">
            <el-input v-model="hotspotForm.ssid" maxlength="32" />
          </el-form-item>
          <el-form-item label="热点密码">
            <el-input
              v-model="hotspotForm.password"
              type="password"
              show-password
              maxlength="63"
              autocomplete="new-password"
              placeholder="留空表示保持原密码"
            />
          </el-form-item>
          <el-form-item label="开机自启">
            <el-switch v-model="hotspotForm.autostart" inline-prompt active-text="开启" inactive-text="关闭" />
          </el-form-item>
          <el-form-item label="无人连接自动关闭">
            <el-input-number v-model="hotspotForm.idle_timeout_minutes" :min="0" :max="1440" :step="5" controls-position="right" />
            <span class="field-unit">分钟，0 表示不自动关闭</span>
          </el-form-item>
        </div>
        <div class="hotspot-footer">
          <div class="hotspot-meta">
            <span>管理地址 <strong>https://192.168.0.1</strong></span>
            <span>热点网卡 <strong>{{ hotspot.device || "wlan1" }}</strong></span>
            <span>自动关闭 <strong>{{ hotspotIdleText }}</strong></span>
          </div>
          <el-button type="primary" :loading="hotspotSaving" @click="saveHotspot(true)">保存热点配置</el-button>
        </div>
      </el-form>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { Delete, Link, Refresh, Search, SwitchButton } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, errorMessage } from "@/api/client";

const formRef = ref();
const hotspotFormRef = ref();
const loading = ref(false);
const scanning = ref(false);
const connecting = ref(false);
const disconnecting = ref(false);
const forgetting = ref(false);
const radioLoading = ref(false);
const hotspotSaving = ref(false);
const hotspotSwitching = ref(false);
const radioEnabled = ref(false);
const hotspotEnabled = ref(false);
const hotspotInitialized = ref(false);
const networks = ref([]);
let refreshTimer;

const wired = reactive({ available: false, connected: false, device: "", addresses: [], gateway: "", mac: "", interfaces: [] });
const wifi = reactive({
  available: false,
  error: "",
  radio_enabled: false,
  devices: [],
  saved_connections: [],
  device: "",
  connected: false,
  connection: "",
  ssid: "",
  addresses: [],
  gateway: "",
  signal: 0,
  security: "",
  frequency: 0,
  autoconnect: false
});
const hotspot = reactive({
  available: false,
  configured: false,
  active: false,
  device: "wlan1",
  ssid: "JVLEI-Gateway",
  address: "192.168.0.1/24",
  autostart: false,
  idle_timeout_minutes: 30,
  clients: 0,
  idle_remaining_seconds: null
});
const wifiForm = reactive({ device: "", ssid: "", password: "", autoconnect: true, hidden: false });
const hotspotForm = reactive({ ssid: "", password: "", autostart: false, idle_timeout_minutes: 30 });

const wiredIp = computed(() => (wired.addresses?.[0] || "").split("/")[0]);
const wifiIp = computed(() => (wifi.addresses?.[0] || "").split("/")[0]);
const wifiClientDevices = computed(() => wifi.devices.filter((item) => !(hotspot.active && item.device === hotspot.device)));
const hotspotIdleText = computed(() => {
  if (!hotspot.active) return "热点未开启";
  if (!hotspot.idle_timeout_minutes) return "已停用";
  if (hotspot.clients) return "有设备连接，暂停计时";
  const seconds = Number(hotspot.idle_remaining_seconds || 0);
  return `${Math.ceil(seconds / 60)} 分钟后关闭`;
});
const requiredRules = (message) => [{ required: true, message, trigger: "change" }];

function applyNetwork(data) {
  Object.assign(wired, data.ethernet || {});
  Object.assign(wifi, data.wifi || {});
  Object.assign(hotspot, data.hotspot || {});
  radioEnabled.value = Boolean(wifi.radio_enabled);
  hotspotEnabled.value = Boolean(hotspot.active);
  if (!wifiForm.device || !wifiClientDevices.value.some((item) => item.device === wifiForm.device)) {
    wifiForm.device = wifi.device || wifiClientDevices.value[0]?.device || "";
  }
  if (wifi.connected && !wifiForm.ssid) {
    wifiForm.ssid = wifi.ssid || wifi.connection;
    wifiForm.autoconnect = Boolean(wifi.autoconnect);
  }
  if (!hotspotInitialized.value) {
    hotspotForm.ssid = hotspot.ssid;
    hotspotForm.autoconnect = Boolean(hotspot.autostart);
    hotspotForm.idle_timeout_minutes = Number(hotspot.idle_timeout_minutes ?? 30);
    hotspotInitialized.value = true;
  }
}

async function loadNetwork(showLoading = false) {
  if (showLoading) loading.value = true;
  try {
    const { data } = await api.get("/api/network");
    applyNetwork(data);
  } catch (error) {
    if (showLoading) ElMessage.error(errorMessage(error, "加载网络状态失败"));
  } finally {
    if (showLoading) loading.value = false;
  }
}

async function scanNetworks() {
  if (!wifiForm.device || scanning.value) return;
  scanning.value = true;
  try {
    const { data } = await api.post("/api/wifi/scan", { device: wifiForm.device });
    networks.value = data.networks || [];
  } catch (error) {
    ElMessage.error(errorMessage(error, "扫描 Wi-Fi 失败"));
  } finally {
    scanning.value = false;
  }
}

async function setRadio(value) {
  if (radioLoading.value) return;
  if (!value && (wifi.connected || hotspot.active)) {
    try {
      await ElMessageBox.confirm("关闭 Wi-Fi 会断开无线网络和维护热点。", "关闭 Wi-Fi", {
        type: "warning",
        confirmButtonText: "确认关闭",
        cancelButtonText: "取消"
      });
    } catch {
      radioEnabled.value = wifi.radio_enabled;
      return;
    }
  }
  radioLoading.value = true;
  try {
    await api.post("/api/wifi/radio", { enabled: Boolean(value) });
    if (!value) networks.value = [];
    await loadNetwork();
    if (value) await scanNetworks();
    ElMessage.success(value ? "Wi-Fi 已开启" : "Wi-Fi 已关闭");
  } catch (error) {
    radioEnabled.value = wifi.radio_enabled;
    ElMessage.error(errorMessage(error, "设置 Wi-Fi 状态失败"));
  } finally {
    radioLoading.value = false;
  }
}

async function connectWifi() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid || connecting.value) return;
  connecting.value = true;
  try {
    const { data } = await api.post("/api/wifi/connect", {
      device: wifiForm.device,
      ssid: wifiForm.ssid,
      password: wifiForm.password,
      autoconnect: wifiForm.autoconnect,
      hidden: wifiForm.hidden
    });
    wifiForm.password = "";
    ElMessage.success(`已连接 ${data.ssid || wifiForm.ssid}`);
    await loadNetwork();
    await scanNetworks();
  } catch (error) {
    ElMessage.error(errorMessage(error, "连接 Wi-Fi 失败"));
  } finally {
    connecting.value = false;
  }
}

async function disconnectWifi() {
  disconnecting.value = true;
  try {
    await api.post("/api/wifi/disconnect", { device: wifi.device });
    await loadNetwork();
    ElMessage.success("Wi-Fi 已断开，自动连接配置仍然保留");
  } catch (error) {
    ElMessage.error(errorMessage(error, "断开 Wi-Fi 失败"));
  } finally {
    disconnecting.value = false;
  }
}

async function forgetWifi() {
  const connection = wifi.connection;
  try {
    await ElMessageBox.confirm(`将断开并删除“${wifi.ssid || connection}”的保存密码。`, "忘记 Wi-Fi", {
      type: "warning",
      confirmButtonText: "断开并忘记",
      cancelButtonText: "取消"
    });
  } catch {
    return;
  }
  forgetting.value = true;
  try {
    await api.post("/api/wifi/forget", { connection });
    wifiForm.password = "";
    await loadNetwork();
    ElMessage.success("已删除保存的 Wi-Fi 配置");
  } catch (error) {
    ElMessage.error(errorMessage(error, "忘记 Wi-Fi 失败"));
  } finally {
    forgetting.value = false;
  }
}

async function saveHotspot(showMessage) {
  const valid = await hotspotFormRef.value?.validate().catch(() => false);
  if (!valid || hotspotSaving.value) return false;
  hotspotSaving.value = true;
  try {
    const { data } = await api.put("/api/hotspot/config", {
      ssid: hotspotForm.ssid,
      password: hotspotForm.password,
      autostart: hotspotForm.autostart,
      idle_timeout_minutes: hotspotForm.idle_timeout_minutes
    });
    hotspotForm.password = "";
    Object.assign(hotspot, data);
    hotspotInitialized.value = false;
    await loadNetwork();
    if (showMessage) ElMessage.success("热点配置已保存");
    return true;
  } catch (error) {
    ElMessage.error(errorMessage(error, "保存热点配置失败"));
    return false;
  } finally {
    hotspotSaving.value = false;
  }
}

async function switchHotspot(value) {
  if (hotspotSwitching.value) return;
  hotspotSwitching.value = true;
  try {
    if (value && !(await saveHotspot(false))) {
      hotspotEnabled.value = hotspot.active;
      return;
    }
    await api.post("/api/hotspot/switch", { enabled: Boolean(value) });
    await loadNetwork();
    ElMessage.success(value ? "维护热点已开启" : "维护热点已关闭");
  } catch (error) {
    hotspotEnabled.value = hotspot.active;
    ElMessage.error(errorMessage(error, value ? "开启热点失败" : "关闭热点失败"));
  } finally {
    hotspotSwitching.value = false;
  }
}

function selectNetwork(row) {
  wifiForm.ssid = row.ssid;
  wifiForm.hidden = false;
}

function networkLabel(item) {
  const band = item.frequency >= 5000 ? "5G" : "2.4G";
  return `${item.ssid} · ${item.signal}% · ${band} · ${item.security}`;
}

function deviceLabel(item) {
  return `${item.device} · ${item.state === "connected" ? "已连接" : "未连接"}`;
}

onMounted(async () => {
  await loadNetwork(true);
  if (wifi.available && wifi.radio_enabled) await scanNetworks();
  refreshTimer = window.setInterval(() => loadNetwork(false), 10000);
});

onBeforeUnmount(() => window.clearInterval(refreshTimer));
</script>
