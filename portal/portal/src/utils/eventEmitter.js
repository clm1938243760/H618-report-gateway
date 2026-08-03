// 弃用, 发布消息不带容错
// import mitt from "mitt";
// export default mitt()

// 来自: 百度AI助手
class EventEmitter {
  constructor() {
    this.events = {};
  }

  on(event, listener) {
    if (!this.events[event]) {
      this.events[event] = [];
    }
    this.events[event].push(listener);
  }

  off(event, listener) {
    if (this.events[event]) {
      this.events[event] = this.events[event].filter((l) => l !== listener);
    }
  }

  emit(event, ...args) {
    if (this.events[event]) {
      this.events[event].forEach((listener) => {
        try {
          listener.call(null, ...args);
        } catch (e) {
          console.error(`An error occurred in listener: ${e.message}`);
        }
      });
    }
  }
}

export { EventEmitter };
export default new EventEmitter();
