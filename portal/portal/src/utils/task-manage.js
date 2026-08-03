// from AI
class TaskManager {
  constructor() {
    this.tasks = new Map();
  }

  /**
   * 某任务是否已存在
   */
  hasTask(taskName) {
    return this.tasks.has(taskName);
  }

  /**
   * 添加任务
   * @param {string} taskName - 任务名称
   * @param {Object} options - 任务配置
   * @returns {boolean} 是否添加成功
   */
  addTask(taskName, options) {
    if (this.tasks.has(taskName)) {
      console.warn(`Task "${taskName}" already exists`);
      return false;
    }

    const task = {
      ...options,
      name: taskName,
      state: "created",
      timerId: null,
      preRun: null,
      lastRun: null,
      executions: 0,
      // 新增执行历史记录
      history: []
    };

    this.tasks.set(taskName, task);

    if (task.autoRun) {
      this.startTask(taskName);
    }
    return true;
  }

  /**
   * 移除单个任务
   * @param {string} taskName - 任务名称
   * @returns {boolean} 是否移除成功
   */
  removeTask(taskName) {
    const task = this.tasks.get(taskName);
    if (!task) return false;

    // 停止任务
    this._clearTaskTimer(task);

    // 执行停止回调
    if (typeof task.onStop === "function") {
      task.onStop(task);
    }

    this.tasks.delete(taskName);
    return true;
  }

  /**
   * 移除所有任务
   */
  removeAllTasks() {
    this.tasks.forEach((task) => {
      this._clearTaskTimer(task);
      if (typeof task.onStop === "function") {
        task.onStop(task);
      }
    });
    this.tasks.clear();
  }

  /**
   * 启动单个任务
   * @param {string} taskName - 任务名称
   * @returns {boolean} 是否启动成功
   */
  startTask(taskName) {
    const task = this.tasks.get(taskName);
    if (!task || task.state === "running") return false;

    // 重置运行时参数
    task.preRun = null;
    task.lastRun = null;
    task.state = "running";
    this._scheduleTask(task);
    return true;
  }

  /**
   * 启动所有任务
   */
  startAllTasks() {
    this.tasks.forEach((task) => {
      if (task.state !== "running") {
        task.state = "running";
        this._scheduleTask(task);
      }
    });
  }

  /**
   * 调度任务执行
   * @private
   * @param {Object} task - 任务对象
   */
  _scheduleTask(task) {
    if (task.state !== "running") return;

    const execute = async () => {
      if (task.state !== "running") return;

      // 记录精确的开始时间
      const runStart = Date.now();

      try {
        task.preRun = runStart;
        task.executions++;

        await task.handler({ meta: task.meta, lastRun: task.lastRun });
      } catch (err) {
        console.error(`Task "${task.name}" failed:`, err);
      } finally {
        // 记录精确的结束时间
        const runEnd = Date.now();
        task.lastRun = runEnd;

        // 保留执行历史（新增）
        task.history.push({
          start: task.preRun,
          end: task.lastRun,
          duration: task.lastRun - task.preRun
        });

        // 清理旧的执行历史（保留最近5次）
        if (task.history.length > 5) {
          task.history.shift();
        }

        // Interval任务重新调度
        if (task.type === "interval" && task.state === "running") {
          const elapsed = Date.now() - runStart;
          const nextDelay = Math.max(task.delay - elapsed, 0);
          task.timerId = setTimeout(execute, nextDelay);
        }
      }
    };

    this._clearTaskTimer(task);

    // 根据类型调度
    if (task.type === "interval") {
      // 立即执行第一次
      execute();
    } else {
      task.timerId = setTimeout(execute, task.delay);
    }
  }

  /**
   * 获取任务信息（改进版）
   * @param {string} taskName - 任务名称
   * @returns {Object|null} 任务信息
   */
  getTask(taskName) {
    const task = this.tasks.get(taskName);
    if (!task) return null;

    return {
      name: task.name,
      type: task.type,
      state: task.state,
      delay: task.delay,
      meta: task.meta,
      preRun: task.preRun,
      lastRun: task.lastRun,
      duration: task.lastRun && task.preRun ? task.lastRun - task.preRun : null,
      executions: task.executions,
      nextRun: this._calcNextRun(task),
      history: [...task.history] // 返回副本
    };
  }

  /**
   * 停止单个任务
   * @param {string} taskName - 任务名称
   * @returns {boolean} 是否停止成功
   */
  stopTask(taskName) {
    const task = this.tasks.get(taskName);
    if (!task || task.state === "stopped") return false;

    task.state = "stopped";
    this._clearTaskTimer(task);

    if (typeof task.onStop === "function") {
      task.onStop(task);
    }

    return true;
  }

  /**
   * 停止所有任务
   */
  stopAllTasks() {
    this.tasks.forEach((task) => {
      if (task.state !== "stopped") {
        task.state = "stopped";
        this._clearTaskTimer(task);
        if (typeof task.onStop === "function") {
          task.onStop(task);
        }
      }
    });
  }

  /**
   * 销毁任务管理器
   */
  destroy() {
    this.stopAllTasks();
    this.removeAllTasks();
  }

  // 计算下次执行时间
  _calcNextRun(task) {
    if (task.state !== "running") return null;

    if (task.type === "interval" && task.lastRun) {
      return task.lastRun + task.delay;
    }

    if (task.type === "timeout" && !task.lastRun) {
      return Date.now() + task.delay;
    }

    return null;
  }

  /**
   * 清除任务定时器
   * @private
   * @param {Object} task - 任务对象
   */
  _clearTaskTimer(task) {
    if (task.timerId) {
      clearTimeout(task.timerId);
      task.timerId = null;
    }
  }
}

// 导出单例实例
const globalTaskManager = new TaskManager();

export { TaskManager };

export default globalTaskManager;
