/**
 * from deepSeek
 */
class WebSocketManager {
  constructor(options = {}) {
    const {
      url = "",
      protocols = [],
      maxReconnectAttempts = 5,
      reconnectDelay = 3000,
      heartbeatInterval = 30000,
      heartbeatMsg = '{"type":"ping"}'
    } = options;

    // 配置参数
    this.url = url;
    this.protocols = protocols;
    this.maxReconnectAttempts = maxReconnectAttempts;
    this.reconnectDelay = reconnectDelay;
    this.heartbeatConfig = { interval: heartbeatInterval, msg: heartbeatMsg };

    // 运行时状态
    this.ws = null;
    this.reconnectCount = 0;
    this.isManualClose = false;
    this.listeners = new Map();
    this.timers = new Set();
  }

  // 主连接方法
  connect() {
    if (this.ws) return;

    this.ws = new WebSocket(this.url, this.protocols);
    this.bindWebSocketEvents();
  }

  // 绑定 WebSocket 原生事件
  bindWebSocketEvents() {
    const handleOpen = (e) => {
      this.resetReconnect();
      this.startHeartbeat();
      this.emit("open", e);
    };

    const handleMessage = (e) => {
      this.emit("message", e.data);
      this.resetHeartbeat();
    };

    const handleError = (e) => {
      this.emit("error", e);
      this.scheduleReconnect();
    };

    const handleClose = (e) => {
      this.emit("close", e);
      if (!this.isManualClose) this.scheduleReconnect();
    };

    const events = [
      ["open", handleOpen],
      ["message", handleMessage],
      ["error", handleError],
      ["close", handleClose]
    ];

    events.forEach(([type, handler]) => {
      this.ws.addEventListener(type, handler);
    });
  }

  // 事件管理
  on(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event).add(callback);
    return this;
  }

  emit(event, ...args) {
    this.listeners.get(event)?.forEach((cb) => {
      try {
        cb(...args);
      } catch (e) {
        console.error(`调用函数 ${cb} 失败, 参数 ${args}`);
      }
    });
  }

  // 重连管理
  scheduleReconnect() {
    if (this.reconnectCount >= this.maxReconnectAttempts) {
      return this.emit("reconnect-failed");
    }

    this.clearTimers("reconnect");
    this.reconnectCount++;

    const timer = setTimeout(() => this.connect(), this.reconnectDelay);
    this.timers.add({ type: "reconnect", ref: timer });
  }

  resetReconnect() {
    this.reconnectCount = 0;
    this.clearTimers("reconnect");
  }

  // 心跳管理
  startHeartbeat() {
    this.clearTimers("heartbeat");

    const timer = setInterval(() => {
      this.ws?.readyState === WebSocket.OPEN && this.ws.send(this.heartbeatConfig.msg);
    }, this.heartbeatConfig.interval);

    this.timers.add({ type: "heartbeat", ref: timer });
  }

  resetHeartbeat() {
    this.clearTimers("heartbeat");
    this.startHeartbeat();
  }

  // 工具方法
  clearTimers(type) {
    for (const timer of this.timers) {
      if (!type || timer.type === type) {
        clearTimeout(timer.ref);
        clearInterval(timer.ref);
        this.timers.delete(timer);
      }
    }
  }

  // 公开方法
  send(data) {
    this.ws?.readyState === WebSocket.OPEN && this.ws.send(data);
  }

  // 手动关闭
  close() {
    this.isManualClose = true;
    this.ws?.close();
    this.clearTimers();
  }

  // 手动重连
  reconnect() {
    this.isManualClose = false;
    this.close();
    this.resetReconnect();
    this.connect();
  }

  // 销毁
  destroy() {
    this.close();
    this.clearTimers();
    this.listeners.clear();
    this.ws = null;
  }
}

export default WebSocketManager;
