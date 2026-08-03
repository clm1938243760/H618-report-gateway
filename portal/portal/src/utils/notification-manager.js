// from AI
class NotificationManager {
  constructor() {
    // 存储不同类型的通知，键为通知类型，值为该类型的通知数组
    this.notifications = {};
  }

  // 创建一类通知
  create(notificationType) {
    if (!this.notifications[notificationType]) {
      this.notifications[notificationType] = [];
    }
  }

  // 获取一类通知
  get(notificationType) {
    return this.notifications[notificationType] || [];
  }

  // 判断是否存在某一类通知
  has(notificationType) {
    return Object.prototype.hasOwnProperty.call(this.notifications, notificationType);
  }

  // 清除同一类所有通知
  clear(notificationType) {
    if (this.notifications[notificationType]) {
      this.executeNotifications(notificationType, "close");
      this.notifications[notificationType] = [];
    }
  }

  // 删除一类通知
  delete(notificationType) {
    if (this.notifications[notificationType]) {
      this.executeNotifications(notificationType, "close");
      delete this.notifications[notificationType];
    }
  }

  // 删除所有通知
  deleteAll() {
    for (const key in this.notifications) {
      this.executeNotifications(key, "close");
    }
    this.notifications = {};
  }

  // 往某一类中添加通知
  // notification: { callback, close, message, context }
  add(notificationType, notification) {
    if (!this.notifications[notificationType]) {
      this.create(notificationType);
    }
    this.notifications[notificationType].push(notification);
  }

  // 执行某一类下的某一个通知
  execute(notificationType, index, directive = "success") {
    const typeNotifications = this.notifications[notificationType];
    if (typeNotifications && index >= 0 && index < typeNotifications.length) {
      const { callback, close, message, context } = typeNotifications[index];

      if (directive === "success") {
        typeof callback === "function" && callback.call(context, message);
      } else if (directive === "close") {
        typeof close === "function" && close.call(context, message);
      }
    }
  }

  // 执行某一类通知
  executeNotifications(notificationType, directive = "success") {
    const typeNotifications = this.notifications[notificationType] || [];
    if (typeNotifications.length) {
      typeNotifications.forEach((item) => {
        const { callback, close, message, context } = item;
        if (directive === "success") {
          typeof callback === "function" && callback.call(context, message);
        } else if (directive === "close") {
          typeof close === "function" && close.call(context, message);
        }
      });
    }
  }
}

export default new NotificationManager();
