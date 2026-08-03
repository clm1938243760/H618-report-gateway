/**
 * 获取对象中指定路径的值
 * @obj Object 对象
 * @desc String 值路径
 */
function getDescendantProp(obj, desc) {
  const arr = desc.split(".");
  let current = obj;
  while (arr.length) {
    current = current[arr.shift()];
  }
  return current;
}

/**
 * @v 时间
 */
function getTime(v) {
  if (Number.isInteger(v)) {
    if (v.length < 10) {
      return new Date(v * 1000);
    }
    return new Date(v);
  }
  if (Date.parse(v)) {
    return new Date(v);
  }
  return "Invalid Date";
}

/**
 * 判断数组 [a,b] 的大小
 * @arr1 Array
 * @arr2 Array
 * @lt String
 */
function compare(arr1, arr2, lt) {
  if (lt === ">") {
    if (arr1[0] > arr2[0]) {
      return true;
    }
    if (arr1[0] == arr2[0]) {
      return arr1[1] >= arr2[1];
    }
    return false;
  }
  if (lt === "<") {
    if (arr1[0] < arr2[0]) {
      return true;
    }
    if (arr1[0] == arr2[0]) {
      return arr1[1] <= arr2[1];
    }
    return false;
  }
}

// 判断时间是否处于时间区间内;
function isTimeInRange(timeStamp, t1, t2, isNight, utcOffset) {
  const date = getTime(timeStamp);

  const minuteMS = 60000;
  const hourMS = 3600000;
  const _timeStamp = date.getTime() - utcOffset * minuteMS;

  const hour = ((_timeStamp % (24 * hourMS)) / hourMS) ^ 0;
  const minute = ((_timeStamp % hourMS) / minuteMS) ^ 0;

  const time1 = t1.split(/[:/-]/);
  const time2 = t2.split(/[:/-]/);

  if (isNight) {
    return (
      (compare([0, 0], [hour, minute], "<") && compare(time1, [hour, minute], ">")) ||
      (compare(time2, [hour, minute], "<") && compare(["23", "59"], [hour, minute], ">"))
    );
  }
  return compare(time1, [hour, minute], "<") && compare(time2, [hour, minute], ">");
}

function encodeHTML(str) {
  const reg = /([&<>"'])/g;
  const codeMap = {
    "&": "&",
    "<": "<",
    ">": ">",
    '"': '"',
    "'": "'"
  };
  return str == undefined
    ? ""
    : `${str}`.replace(reg, function (s, c) {
        return codeMap[c];
      });
}

function decodeHTML(str) {
  const reg = /(&|<|>|"|')/g;
  const codeMap = {
    "&": "&",
    "<": "<",
    ">": ">",
    '"': '"',
    "'": "'"
  };
  return str == undefined
    ? ""
    : `${str}`.replace(reg, function (s, c) {
        return codeMap[c];
      });
}

function isPrimitiveValue(value) {
  return (
    typeof value === "number" ||
    typeof value === "string" ||
    typeof value === "boolean" ||
    typeof value === "undefined" ||
    typeof value === "symbol" ||
    typeof value === "bigint" ||
    (typeof value === "object" && value === null)
  );
}

// 深拷贝
function deepCopy(obj) {
  let copy;

  // Handle the 3 simple types, and null or undefined
  if (obj == null || typeof obj !== "object") return obj;

  // Handle Date
  if (obj instanceof Date) {
    copy = new Date();
    copy.setTime(obj.getTime());
    return copy;
  }

  // Handle Array
  if (obj instanceof Array) {
    copy = [];
    for (let i = 0, len = obj.length; i < len; i++) {
      copy[i] = deepCopy(obj[i]);
    }
    return copy;
  }

  // Handle Object
  if (obj instanceof Object) {
    copy = {};
    for (const attr in obj) {
      // eslint-disable-next-line no-prototype-builtins
      if (obj.hasOwnProperty(attr)) copy[attr] = deepCopy(obj[attr]);
    }
    return copy;
  }

  if (isPrimitiveValue(obj)) {
    copy = obj;
    return copy;
  }
  throw new Error("Unable to copy obj! Its type isn't supported.");
}

// 对 week 的一步反运算, 计算情况: 2019,3: 2019年第3周, 对应是哪天到哪天;
function getWeekRange(year, week, tpl) {
  const day_miliseconds = 86400000;
  const onejan = new Date(year, 0, 1, 0, 0, 0);
  const onejan_day = onejan.getDay() == 0 ? 7 : onejan.getDay();
  const days_for_next_monday = 8 - onejan_day;
  const onejan_next_monday_time = onejan.getTime() + days_for_next_monday * day_miliseconds;
  const first_monday_year_time = onejan_day > 1 ? onejan_next_monday_time : onejan.getTime();
  const target_week_monday_time = first_monday_year_time + day_miliseconds * 7 * (week - 1);
  const target_week_sunday_time = target_week_monday_time + day_miliseconds * 6 - 1000;

  return [dateFormat(target_week_monday_time, tpl || "yyyy-MM-dd"), dateFormat(target_week_sunday_time, tpl || "yyyy-MM-dd")];
}

/**
 * 日期格式化成字符串
 */
function dateFormat(date, fmt) {
  !fmt && (fmt = "yyyy/MM/dd hh:mm:ss");
  if (typeof date === "number") {
    date = date.toString().substr(0, 13);
  }
  if (typeof data === "string") {
    date = new Date(parseInt(date, 10));
  }
  const o = {
    "M+": date.getMonth() + 1, // 月份
    "d+": date.getDate(), // 日
    "h+": date.getHours(), // 小时
    "m+": date.getMinutes(), // 分
    "s+": date.getSeconds(), // 秒
    "q+": Math.floor((date.getMonth() + 3) / 3), // 季度
    S: date.getMilliseconds() // 毫秒
  };
  if (/(y+)/.test(fmt)) {
    fmt = fmt.replace(RegExp.$1, `${date.getFullYear()}`.substr(4 - RegExp.$1.length));
  }
  for (const k in o) {
    if (new RegExp(`(${k})`).test(fmt)) {
      fmt = fmt.replace(RegExp.$1, RegExp.$1.length === 1 ? o[k] : `00${o[k]}`.substr(`${o[k]}`.length));
    }
  }
  return fmt;
}

// 获取周: 一个月最多可以跨 6周, 31天, 首尾恰好位于起始时间
// from: https://stackoverflow.com/questions/9045868/javascript-date-getweek
function getWeek(timeStr) {
  const _this = new Date(timeStr);
  // We have to compare against the first monday of the year not the 01/01
  // 60*60*24*1000 = 86400000
  // 'onejan_next_monday_time' reffers to the miliseconds of the next monday after 01/01

  const day_miliseconds = 86400000;
  const onejan = new Date(_this.getFullYear(), 0, 1, 0, 0, 0);
  const onejan_day = onejan.getDay() == 0 ? 7 : onejan.getDay();
  const days_for_next_monday = 8 - onejan_day;
  const onejan_next_monday_time = onejan.getTime() + days_for_next_monday * day_miliseconds;
  // If one jan is not a monday, get the first monday of the year
  const first_monday_year_time = onejan_day > 1 ? onejan_next_monday_time : onejan.getTime();
  const this_date = new Date(_this.getFullYear(), _this.getMonth(), _this.getDate(), 0, 0, 0); // This at 00:00:00
  const this_time = this_date.getTime();
  const days_from_first_monday = Math.round((this_time - first_monday_year_time) / day_miliseconds);

  // var first_monday_year = new Date(first_monday_year_time);

  // We add 1 to "days_from_first_monday" because if "days_from_first_monday" is *7,
  // then 7/7 = 1, and as we are 7 days from first monday,
  // we should be in week number 2 instead of week number 1 (7/7=1)
  // We consider week number as 52 when "days_from_first_monday" is lower than 0,
  // that means the actual week started before the first monday so that means we are on the firsts
  // days of the year (ex: we are on Friday 01/01, then "days_from_first_monday"=-3,
  // so friday 01/01 is part of week number 52 from past year)
  // "days_from_first_monday<=364" because (364+1)/7 == 52, if we are on day 365, then (365+1)/7 >= 52 (Math.ceil(366/7)=53) and thats wrong

  return days_from_first_monday >= 0 && days_from_first_monday < 364 ? Math.ceil((days_from_first_monday + 1) / 7) : 52;
}

/**
 * 全屏
 * @param elem dom元素
 */
function fullscreen(elem) {
  const docElm = elem || document.documentElement;
  if (docElm.requestFullscreen) {
    docElm.requestFullscreen();
  } else if (docElm.mozRequestFullScreen) {
    docElm.mozRequestFullScreen();
  } else if (docElm.webkitRequestFullScreen) {
    docElm.webkitRequestFullScreen();
  } else if (docElm.msRequestFullscreen) {
    docElm.msRequestFullscreen();
  }
}

/**
 * 退出全屏
 */
function exitFullscreen() {
  if (document.exitFullscreen) {
    document.exitFullscreen();
  } else if (document.mozCancelFullScreen) {
    document.mozCancelFullScreen();
  } else if (document.webkitCancelFullScreen) {
    document.webkitCancelFullScreen();
  } else if (document.msExitFullscreen) {
    document.msExitFullscreen();
  }
}

/**
 * 比较两个对象是否相同
 */
function deepEqual(x, y) {
  const core_toString = Object.prototype.toString;
  const ta = core_toString.call(x);
  const tb = core_toString.call(y);

  if (x === y) {
    return true;
  }
  if (ta !== tb) {
    return false;
  }
  if (!(typeof x === "object" && x != null) || !(typeof y === "object" && y != null)) {
    return false;
  }

  if (Object.keys(x).length != Object.keys(y).length) {
    return false;
  }
  for (const prop in x) {
    // eslint-disable-next-line no-prototype-builtins
    if (y.hasOwnProperty(prop)) {
      if (!deepEqual(x[prop], y[prop])) {
        return false;
      }
    } else {
      return false;
    }
  }

  return ta === "[object Date]" ? x.valueOf() == y.valueOf() : true;
}

/**
 * 下载文件
 * @param blob 接口返回的数据
 * @param name 文件名
 * @param postfix 后缀名(默认 .xlsx)
 */
function downloadBlob(blob, name, postfix = ".xlsx") {
  if (navigator.msSaveOrOpenBlob) {
    navigator.msSaveOrOpenBlob(blob, name + postfix);
  } else {
    const reader = new FileReader();
    reader.readAsDataURL(blob);
    reader.onload = function (e) {
      const a = document.createElement("a");
      a.download = name;
      a.href = e.target.result;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    };
  }
}

/**
 * 以 base64 格式获取文件内容
 */
function getFileBase64(file) {
  // 获取图片转base64
  return new Promise(function (resolve, reject) {
    const reader = new FileReader();
    let imgResult = "";
    reader.readAsDataURL(file);
    reader.onload = function () {
      imgResult = reader.result;
    };
    reader.onerror = function (error) {
      reject(error);
    };
    reader.onloadend = function () {
      resolve(imgResult);
    };
  });
}

function isPlainObject(val) {
  return Object.prototype.toString.call(val) === "[object Object]";
}

/**
 * 将 base64 内容转为 Blob
 */
function transBase64DataToBlob(base64Data, mimeType) {
  const binaryString = window.atob(base64Data);
  const binaryLen = binaryString.length;
  const bytes = new Uint8Array(binaryLen);

  for (let i = 0; i < binaryLen; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }

  return new Blob([bytes], mimeType || {});
}

/**
 * 将 base64 内容转为 File
 */
function transBase64DataToFile(base64Data, name, mimeType) {
  const binaryString = window.atob(base64Data);
  const binaryLen = binaryString.length;
  const bytes = new Uint8Array(binaryLen);

  for (let i = 0; i < binaryLen; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }

  const blob = new Blob([bytes], mimeType || {});
  return new File([blob], name, { type: blob.type });
}

/**
 * 下载一个 base64 文件
 */
function downloadBase64File(base64Data, fileName) {
  downloadBlob(transBase64DataToBlob(base64Data), fileName);
}

/**
 * 在树结构中寻找匹配的节点
 * @param treeNodes: Object | Array, 要遍历的节点
 * @param matchRule: Function, 匹配的规则函数
 * @param childrenKey: String, 子节点的 key
 */
function findNodeInTree(treeNode, matcher, childKey, pNode = null, maxLevel = Infinity) {
  function traverse(nodes, parent, level) {
    if (level > maxLevel) {
      return null;
    }

    if (!Array.isArray(nodes)) {
      nodes = [nodes];
    }

    for (let i = 0; i < nodes.length; i++) {
      const node = nodes[i];
      if (matcher(node, parent, level)) {
        return node;
      }

      if (node[childKey]) {
        const found = traverse(node[childKey], node, level + 1);
        if (found) {
          return found;
        }
      }
    }

    return null;
  }

  return traverse(treeNode, pNode, 1);
}

/**
 * 遍历树节点
 * @param treeNode: Object | Array, 要遍历的节点
 * @param callback: Function 遍历每个节点时, 要执行的函数
 * @param child: String, 子节点的 key
 * @param initLevel: Number 设置节点遍历层级初始值, 默认为 0
 */
function travalNode(treeNode, callback, child = "children", initLevel = 0) {
  if (isPlainObject(treeNode)) {
    typeof callback === "function" && callback(treeNode, initLevel);
    if (treeNode[child]) {
      travalNode(treeNode[child], callback, child, initLevel + 1);
    }
  } else if (Array.isArray(treeNode)) {
    for (let i = 0; i < treeNode.length; i++) {
      travalNode(treeNode[i], callback, child, initLevel);
    }
  }
}

/**
 * 获取 url 查询参数
 * @param url: String, 查询字符串, 会以第一个 ? 号后面出现的字符作为查询参数
 * @param key: String, 查询参数字段, 如果不传默认会返回整个解析后的查询参
 * @return Object | String, 完整的查询参或指定 key 的值
 */
function getUrlParams(url, key) {
  const urlStr = url.split("?")[1];
  const obj = {};
  if (!urlStr) {
    return key ? obj[key] : obj;
  }
  const paramsArr = urlStr.split("&");
  for (let i = 0, len = paramsArr.length; i < len; i++) {
    const arr = paramsArr[i].split("=");
    obj[arr[0]] = decodeURIComponent(arr[1]);
  }
  return key ? obj[key] : obj;
}

function getUrlHash(url) {
  const urlStr = url.match(/#([^#?]+)/);
  return urlStr ? urlStr[1] : "";
}

// 判断类型
const INI_CAPITAL_WORD = /[A-Z][a-z]+/;
function getValueType(input) {
  return Object.prototype.toString.call(input).match(INI_CAPITAL_WORD)[0].toLowerCase();
}
const isFunction = (val) => typeof val === "function";
const isUndefined = (val) => typeof val === "undefined";
const isString = (val) => typeof val === "string";
const isNumber = (val) => typeof val === "number";
const isArray = (val) => getValueType(val) === "array";

// 拼接查询参数
function resolveQueryUrl(url, query) {
  const [path, queryStr] = url.split("?");
  const oldQuery = queryStr ? getUrlParams(`?${queryStr}`) : null;

  let newQuery;
  if (isString(query)) {
    if (query) {
      newQuery = getUrlParams(`?${query}`);
    }
  } else if (isPlainObject(query)) {
    newQuery = query;
  }

  const assignQuery = merge({}, oldQuery || {}, newQuery || {});

  let qs = "";
  for (const key in assignQuery) {
    qs += `&${key}=${assignQuery[key]}`;
  }

  return `${path}${qs ? `?${qs.slice(1)}` : ""}`;
}

/**
 * 过滤请求参数中的空值: 空值包括: undefined, null, '', []
 * @param obj: Object 要过滤的对象
 * @return Object 过滤之后的新对象
 */
function filterQueryEmptyValue(obj) {
  if (!obj) {
    return obj;
  }

  const res = {};
  const emptyValues = ["", undefined, null];
  for (const key in obj) {
    const val = obj[key];
    if (emptyValues.includes(val) || (Array.isArray(val) && val.length === 0)) {
      // 清除
      continue;
    }

    res[key] = val;
  }

  return res;
}

/**
 * 计算数值 a 以 b为底的对数
 */
function getLog(a, b) {
  // 使用 Math.log() 计算以 e 为底的对数
  const naturalLog = Math.log(a);

  // 使用 Math.log() 计算以 b 为底的对数，并除以以 e 为底的对数
  const baseLog = naturalLog / Math.log(b);

  // 返回结果
  return baseLog;
}

/**
 * 转换文件大小
 */
function getFileSie(v) {
  if (["", undefined, null].includes(v)) {
    return "";
  }

  const size = Number(v);
  if (!Number.isFinite(size)) {
    return "";
  }

  if (size === 0) {
    return `${0}B`;
  }

  const units = {
    0: "B",
    1: "K",
    2: "M",
    3: "G",
    4: "T",
    5: "P"
  };
  const log1024 = getLog(size, 1024);
  const unit = Math.floor(log1024);
  const _size = size / 1024 ** Math.floor(log1024);
  return (Number.isInteger(_size) ? _size : _size.toFixed(2)) + units[unit];
}

/**
 * 以队列的形式（先进先出）执行批量任务
 * @limit 单批次执行任务数量
 * @async 单批次执行的方式, 同步或是异步执行, true 异步, false 同步
 * @nextWaiting 每一个批次执行的间隔时间
 * @attachBatch 是否增加当前批次任务执行完毕时的回调, 如果增加了需要手动实现 onBatchEnd 的监听函数
 * @attachEnd 类似上面
 */
class Quene {
  constructor(limit, async, nextWaiting, attachBatch, attachEnd) {
    this.quene = [];
    this.count = 0;
    this.allCount = 0;
    this.limit = limit || Infinity;
    this.waiting = nextWaiting || 0;
    this.async = async || false;
    this.result = [];
    this.attachEnd = attachEnd || false;
    this.attachBatch = attachBatch || false;
  }

  enquene(tasks) {
    if (Array.isArray(tasks)) {
      tasks.forEach((v) => {
        typeof v === "function" && this.quene.push(v);
      });
      this.allCount += tasks.length;
    } else if (typeof tasks === "function") {
      this.quene.push(tasks);
      this.allCount++;
    }
  }

  dequene() {
    return this.quene.shift();
  }

  clear() {
    while (this.quene.length) {
      this.dequene();
    }
  }

  asyncInvoke(fn) {
    return new Promise((resolve, reject) => {
      const _this = this;
      const transfer = async function () {
        try {
          const res = await fn(_this.result);
          _this.result.push(res);
        } catch (e) {
          console.error(`函数 ${fn} 执行错误`, e);
        }
        resolve();
      };

      transfer();
    });
  }

  onBatchEnd() {
    console.error("quene onBatchEnd not implemented");
  }

  onAllEnd() {
    console.error("quene onAllEnd not implemented");
  }

  run() {
    if (this.async) {
      for (let i = 0; i < this.limit; i++) {
        const task = this.dequene();
        if (!task) {
          this.result.length = 0;
          return;
        }
        if (this.allCount === 0) {
          return;
        }

        this.asyncInvoke(task).then(() => {
          this.count++;
          this.allCount--;

          if (this.allCount === 0) {
            if (this.count) {
              this.attachBatch && this.onBatchEnd();
            }
            this.attachEnd && this.onAllEnd();
            return;
          }

          if (this.count === this.limit) {
            this.attachBatch && this.onBatchEnd();
            setTimeout(() => {
              this.count = 0;
              this.result = [];
              this.run();
            }, this.waiting);
          }
        });
      }
    } else {
      const task = this.dequene();
      if (!task) {
        this.result.length = 0;
        return;
      }
      if (this.allCount === 0) {
        return;
      }

      this.asyncInvoke(task).then(() => {
        this.count++;
        this.allCount--;

        if (this.allCount === 0) {
          if (this.count) {
            this.attachBatch && this.onBatchEnd();
          }
          this.attachEnd && this.onAllEnd();
          return;
        }

        if (this.count === this.limit) {
          this.attachBatch && this.onBatchEnd();
          setTimeout(() => {
            this.run();
            this.count = 0;
            this.result = [];
          }, this.waiting);
        } else {
          this.run();
        }
      });
    }
  }
}

/**
 * 递归合并对象
 * @param {target} 要合并的对象, 可传入多个, 最终结果会合并到第一个对象中
 * @return {}
 *
 * merge({}, obj1, obj2);
 */
function merge(target) {
  // 获取除第一个参数外的其余参数
  const sources = [].slice.call(arguments, 1);

  // 如果没有源对象，直接返回目标对象
  if (!sources.length) return target;

  // 从源对象中取出第一个
  const source = sources.shift();

  // 遍历源对象中的所有可枚举属性
  if (isPlainObject(source)) {
    for (const key in source) {
      if (Object.prototype.hasOwnProperty.call(source, key)) {
        // 如果属性值是对象，则递归合并
        if (isPlainObject(source[key])) {
          target[key] = merge(target[key] || {}, source[key]);
        } else if (isArray(source[key])) {
          if (isArray(target[key])) {
            for (let i = 0; i < source[key].length; i++) {
              const leftType = getValueType(target[key][i]);
              const rightType = getValueType(source[key][i]);

              if (leftType !== rightType) {
                target[key][i] = source[key][i];
              } else if (leftType === "object" || leftType === "array") {
                target[key][i] = merge(target[key][i], source[key][i]);
              } else {
                target[key][i] = source[key][i];
              }
            }
          } else {
            target[key] = source[key];
          }
        } else {
          // 如果属性值不是对象，直接赋值
          target[key] = source[key];
        }
      }
    }
  } else if (isArray(source)) {
    for (let i = 0; i < source.length; i++) {
      if (isPlainObject(source[i]) || isArray(source[i])) {
        target[i] = merge(target[i] || {}, source[i]);
      } else {
        // 如果属性值不是对象，直接赋值
        target[i] = source[i];
      }
    }
  }

  return merge.apply(null, [target].concat(sources));
  // return merge(target, ...sources);
}

function filterEmptyParams(parame) {
  const newParams = {};
  const emptyVals = ["", undefined, null];
  Object.keys(parame)?.forEach((key) => {
    if (!emptyVals.includes(parame[key])) {
      newParams[key] = parame[key];
    }
  });
  return newParams;
}

/**
 * 获取数组中匹配项
 */
function getMatchItem(list, matchObj, exportKey) {
  const arr = list || [];
  const item = list.find((v) => {
    let isMatch = 1;
    for (const key in matchObj) {
      isMatch &= matchObj[key] === v[key];
    }
    return isMatch;
  });

  if (item) {
    return exportKey ? item[exportKey] : item;
  }
}

/**
 * 将分钟转为 天-小时-分钟
 */
function minuteToDayHours(ms, emptyText) {
  if (ms == 0) {
    return emptyText || "0";
  }

  const day = Math.floor((ms / (60 * 24)) % 24);
  const hour = Math.floor((ms / 60) % 24);
  const minite = Math.floor(ms % 60);

  return `${day === 0 ? "" : `${day}天`}${hour === 0 ? "" : `${hour}小时`}${minite === 0 ? "" : `${minite}分钟`}`;
}

function getScreenDPI() {
  const testElement = document.createElement("div");
  testElement.style.width = "1in";
  document.body.appendChild(testElement);
  const dpi = testElement.offsetWidth * window.devicePixelRatio;
  document.body.removeChild(testElement);
  return dpi;
}

function getPaperPixels(paperSize, dpi) {
  const mmToInch = 25.4;
  const paperSizes = {
    A1: [594, 841],
    A2: [420, 594],
    A3: [297, 420],
    A4: [210, 297]
  };

  if (!paperSizes[paperSize]) {
    console.error("不支持的纸张尺寸，请输入 A1、A2、A3 或 A4。");
    return null;
  }

  const [widthInMm, heightInMm] = paperSizes[paperSize];
  const widthInPixels = Math.round((widthInMm * dpi) / mmToInch);
  const heightInPixels = Math.round((heightInMm * dpi) / mmToInch);

  return {
    width: widthInPixels,
    height: heightInPixels
  };
}

// String.prototype.substr 方法的 Polyfill, 该方法出于兼容性而保留;
function substrPolyfill(str, start, length) {
  const strLength = str.length;

  // 处理 start 参数
  if (start < 0) {
    start = Math.max(strLength + start, 0);
  } else {
    start = Math.min(start, strLength);
  }

  // 处理 length 参数
  if (typeof length === "undefined") {
    length = strLength - start;
  } else if (length < 0) {
    return "";
  }

  let result = "";
  const end = start + length;
  for (let i = start; i < end && i < strLength; i++) {
    result += str[i];
  }
  return result;
}

/**
 * 展示时间
 */
function parseTime(timeStr, format) {
  const date = new Date(timeStr);
  const year = date.getFullYear();
  const month = date.getMonth() + 1; // .padStart(2, '0');
  const day = date.getDate();
  const hour = date.getHours();
  const minute = date.getMinutes();
  const second = date.getSeconds();
  const weekDay = ["日", "一", "二", "三", "四", "五", "六"][date.getDay()];

  const replacements = {
    Y: year,
    M: month,
    D: day,
    h: hour,
    m: minute,
    s: second,
    w: weekDay
  };

  return format.replace(/\{([YMDhmsw]+)\}/g, (match, $1) => {
    let val = replacements[$1[0]];
    if ($1.length > 1) {
      val = `${val}`.padStart(2, "0");
    }
    return val;
  });
}

/**
 * 将样式声明对象转换为 style 文本
 */
function convertCssObjectsToStyleText(cssObjects) {
  let styleText = "";
  cssObjects.forEach((cssObj) => {
    const { selector, style } = cssObj;
    let singleStyleText = "";
    for (const property in style) {
      if (Object.prototype.hasOwnProperty.call(style, property)) {
        const camelCaseToKebabCase = property.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();
        singleStyleText += `${camelCaseToKebabCase}:${style[property]};`;
      }
    }
    styleText += `${selector} { ${singleStyleText} }`;
  });
  return styleText;
}

/**
 * 预览某 dom 元素
 */
function printElement({ selector, printStyle, callback, htmlParser }) {
  const element = document.querySelector(selector);
  if (!element) {
    console.error("未找到指定 ID 的元素");
    return;
  }

  const printWindow = window.open("", "_blank", "configration");
  const htmlContent = `
        <html>
        <head>
            <title>打印预览</title>
        </head>
        <body>
            <style>
              *,
              *::before,
              *::after { 
                box-sizing: border-box;
                margin: 0;
                padding: 0; 
              }
              @media print {
                /* 隐藏页眉和页脚 */
                @page {
                  margin-top: 0;
                  margin-bottom: 0;
                }
              }
            </style>
            <style>
                /* 复制内联样式 */
                ${printStyle ? convertCssObjectsToStyleText(printStyle) : ""}
            </style>
            ${element.outerHTML}
        </body>
        </html>
    `;

  printWindow.document.open();
  printWindow.document.write(typeof htmlParser === "function" ? htmlParser(htmlContent) : htmlContent);
  printWindow.document.close();

  // eslint-disable-next-line func-names
  printWindow.onload = function () {
    typeof callback === "function" && callback.call(null, printWindow);
    // printWindow.print();
    // printWindow.close();
  };
}

/**
 * 删除 html 文本中指定的属性-值
 */
function removeAttributesFromHtml(html, attributesToRemove) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, "text/html");

  const allElements = doc.getElementsByTagName("*");
  for (let i = 0; i < allElements.length; i++) {
    const element = allElements[i];
    attributesToRemove.forEach((attr) => {
      if (element.hasAttribute(attr)) {
        element.removeAttribute(attr);
      }
    });
  }

  return doc.body.innerHTML;
}

function FilteringEmptyDataByZero(parame) {
  const newParams = {};
  Object.keys(parame)?.forEach((key) => {
    if (parame[key] || parame[key] === 0) {
      newParams[key] = parame[key];
    }
  });
  return newParams;
}

function calculateTimeDuration(givenTime) {
  // 将给定时间字符串转换为 Date 对象
  const givenDate = new Date(givenTime);
  // 获取当前时间
  const currentDate = new Date();

  // 计算时间差（毫秒）
  const timeDifference = currentDate - givenDate;

  // 计算天数、小时数和分钟数
  const oneDay = 24 * 60 * 60 * 1000;
  const oneHour = 60 * 60 * 1000;
  const oneMinute = 60 * 1000;

  const days = Math.floor(timeDifference / oneDay);
  const remainingAfterDays = timeDifference % oneDay;
  const hours = Math.floor(remainingAfterDays / oneHour);
  const remainingAfterHours = remainingAfterDays % oneHour;
  const minutes = Math.floor(remainingAfterHours / oneMinute);

  let result = "";
  if (days > 0) {
    result += `${days} 天`;
  }
  if (hours > 0) {
    result += `${hours} 小时`;
  }
  if (minutes > 0) {
    result += `${minutes} 分钟`;
  }

  return result || "不到 1 分钟";
}

function getMonday(date) {
  const day = date.getDay();
  const diff = date.getDate() - day + (day === 0 ? -6 : 1);
  return new Date(date.setDate(diff));
}

function getFirstDayOfMonth(date) {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function getLastDayOfMonth(date) {
  return new Date(date.getFullYear(), date.getMonth() + 1, 0);
}

function formatDate(date, isEnd = false) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  if (isEnd) {
    return `${year}-${month}-${day} 23:59:59`;
  }
  return `${year}-${month}-${day} 00:00:00`;
}

/**
 * @copyright from element-ui/src/utils/util.js
 * 以 字符串形式 获取对象上对应属性的值
 * @param {Object} object 要获取值的对象
 * @param {Object} prop 要获取的属性路径
 */
function getValueByPath(object, prop) {
  prop = prop || "";
  const paths = prop.split(".");
  let current = object;
  let result = null;
  for (let i = 0, j = paths.length; i < j; i++) {
    const path = paths[i];
    if (!current) break;

    if (i === j - 1) {
      result = current[path];
      break;
    }
    current = current[path];
  }
  return result;
}

/**
 * 获取范围时间
 * @param {String} tag 选择标识;
 */
function getDateTimeRange(distance, isLastSecond) {
  const now = new Date();
  let startDate;
  let endDate;
  let isSameDay;

  if (typeof distance === "number") {
    if (distance > 0) {
      startDate = new Date(now);
      endDate = new Date(now);
      endDate.setDate(endDate.getDate() + distance);
    } else if (distance === 0) {
      startDate = new Date(now);
      startDate.setHours(0, 0, 0, 0);
      endDate = new Date(now);
      isSameDay = true;
    } else {
      startDate = new Date(now);
      startDate.setDate(startDate.getDate() + distance);
      endDate = new Date(now);
    }
  } else {
    switch (distance) {
      case "上周": {
        const lastWeekStart = new Date(now);
        lastWeekStart.setDate(lastWeekStart.getDate() - 7);
        startDate = getMonday(lastWeekStart);
        endDate = new Date(startDate);
        endDate.setDate(endDate.getDate() + 6);
        break;
      }
      case "本周": {
        startDate = getMonday(now);
        endDate = new Date(startDate);
        endDate.setDate(endDate.getDate() + 6);
        break;
      }
      case "当月": {
        startDate = getFirstDayOfMonth(now);
        endDate = getLastDayOfMonth(now);
        break;
      }
      case "上月": {
        const lastMonth = new Date(now);
        lastMonth.setMonth(lastMonth.getMonth() - 1);
        startDate = getFirstDayOfMonth(lastMonth);
        endDate = getLastDayOfMonth(lastMonth);
        break;
      }
      case "最近三个月": {
        const threeMonthsAgo = new Date(now);
        threeMonthsAgo.setMonth(threeMonthsAgo.getMonth() - 2);
        startDate = getFirstDayOfMonth(threeMonthsAgo);
        endDate = getLastDayOfMonth(now);
        break;
      }
      case "七天": {
        startDate = new Date(now);
        startDate.setDate(startDate.getDate() - 6);
        endDate = new Date(now);
        break;
      }
      case "三天": {
        startDate = new Date(now);
        startDate.setDate(startDate.getDate() - 2);
        endDate = new Date(now);
        break;
      }
      case "昨天": {
        startDate = new Date(now);
        startDate.setDate(startDate.getDate() - 1);
        startDate.setHours(0, 0, 0, 0);
        endDate = new Date(startDate);
        break;
      }
      case "今天": {
        startDate = new Date(now);
        startDate.setHours(0, 0, 0, 0);
        endDate = new Date(now);
        isSameDay = true;
        break;
      }
      case "当年": {
        startDate = new Date(now.getFullYear(), 0, 1);
        endDate = new Date(now.getFullYear(), 11, 31);
        break;
      }
      case "去年": {
        const lastYear = new Date(now);
        lastYear.setFullYear(lastYear.getFullYear() - 1);
        startDate = new Date(lastYear.getFullYear(), 0, 1);
        endDate = new Date(lastYear.getFullYear(), 11, 31);
        break;
      }
      case "下周": {
        const nextWeekStart = new Date(now);
        nextWeekStart.setDate(nextWeekStart.getDate() + 7);
        startDate = getMonday(nextWeekStart);
        endDate = new Date(startDate);
        endDate.setDate(endDate.getDate() + 6);
        break;
      }
      case "明年": {
        const nextYear = new Date(now);
        nextYear.setFullYear(nextYear.getFullYear() + 1);
        startDate = new Date(nextYear.getFullYear(), 0, 1);
        endDate = new Date(nextYear.getFullYear(), 11, 31);
        break;
      }
      default: {
        throw new Error("不支持的 distance 参数");
      }
    }
  }

  return [formatDate(startDate), formatDate(endDate, isSameDay || isLastSecond)];
}

function isSameArray(arr1, arr2) {
  if (arr1.length !== arr2.length) {
    return false;
  }
  for (let i = 0; i < arr1.length; i++) {
    if (arr1[i] !== arr2[i]) {
      return false;
    }
  }
  return true;
}

function convertToCamelCase(str) {
  // 匹配 - 或 / 作为分隔符
  const parts = str.split(/[-/]/);
  let result = "";
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    // 将每个部分的首字母大写，其余字母小写
    result += part.charAt(0).toUpperCase() + part.slice(1).toLowerCase();
  }
  return result;
}

function getNearYears(year, offset) {
  const years = [];
  if (offset === 0) {
    years.push(year);
  } else if (offset > 0) {
    for (let i = 0; i <= offset; i++) {
      years.push(year + i);
    }
  } else {
    for (let i = offset; i <= 0; i++) {
      years.push(year + i);
    }
  }
  return years;
}

/**
 * 复制DOM元素到DocumentFragment并过滤指定元素
 * @param {HTMLElement} sourceEl - 源DOM元素
 * @param {string|string[]} selectorsToRemove - 要移除的元素的CSS选择器或选择器数组
 * @param {boolean} [deep=true] - 是否深复制（默认true）
 * @returns {DocumentFragment} - 包含复制内容的DocumentFragment
 */
function cloneElementToFragment(sourceEl, selectorsToRemove, deep = true) {
  // 创建DocumentFragment
  const fragment = document.createDocumentFragment();

  // 复制源元素
  const clonedEl = sourceEl.cloneNode(deep);

  // 如果没有提供选择器，直接返回克隆的元素
  if (!selectorsToRemove) {
    fragment.appendChild(clonedEl);
    return fragment;
  }

  // 将选择器转换为数组
  const selectors = Array.isArray(selectorsToRemove) ? selectorsToRemove : [selectorsToRemove];

  // 移除匹配选择器的元素
  selectors.forEach((selector) => {
    clonedEl.querySelectorAll(selector).forEach((el) => {
      el.remove();
    });
  });

  // 将处理后的克隆元素添加到DocumentFragment
  fragment.appendChild(clonedEl);

  return fragment;
}

function getPlatForm() {
  var inBrowser = typeof window !== "undefined";
  // eslint-disable-next-line no-undef
  var inWeex = typeof WXEnvironment !== "undefined" && !!WXEnvironment.platform;
  // eslint-disable-next-line no-undef
  var weexPlatform = inWeex && WXEnvironment.platform.toLowerCase();
  var UA = inBrowser && window.navigator.userAgent.toLowerCase();
  var isIE = UA && /msie|trident/.test(UA);
  var isIE9 = UA && UA.indexOf("msie 9.0") > 0;
  var isEdge = UA && UA.indexOf("edge/") > 0;
  var isAndroid = (UA && UA.indexOf("android") > 0) || weexPlatform === "android";
  var isIOS = (UA && /iphone|ipad|ipod|ios/.test(UA)) || weexPlatform === "ios";
  var isChrome = UA && /chrome\/\d+/.test(UA) && !isEdge;
  var isPhantomJS = UA && /phantomjs/.test(UA);
  var isFF = UA && UA.match(/firefox\/(\d+)/);
  var isMobile = UA && UA.match(/Mobile|iphone/i);
  var isPad = UA && UA.match(/ipad/i);
  return {
    inBrowser,
    inWeex,
    weexPlatform,
    UA,
    isIE,
    isIE9,
    isEdge,
    isAndroid,
    isIOS,
    isChrome,
    isPhantomJS,
    isFF,
    isMobile,
    isPad
  };
}

/**
 * 判断当前运行环境
 * @returns {string} 环境标识（如 'ios', 'android', 'web', 'wechat-miniprogram', 'alipay-miniprogram' 等）
 */
function getCurrentEnv() {
  // 小程序环境优先判断（部分小程序环境中 window 对象可能不存在）
  // eslint-disable-next-line no-undef
  if (typeof wx !== "undefined" && typeof wx.getSystemInfoSync === "function") {
    // 微信小程序环境
    return "wechat-miniprogram";
  }
  // eslint-disable-next-line no-undef
  if (typeof my !== "undefined" && typeof my.getSystemInfoSync === "function") {
    // 支付宝小程序环境
    return "alipay-miniprogram";
  }
  // eslint-disable-next-line no-undef
  if (typeof swan !== "undefined" && typeof swan.getSystemInfoSync === "function") {
    // 百度智能小程序环境
    return "baidu-miniprogram";
  }

  // 非小程序环境（H5/浏览器），通过 userAgent 判断
  if (typeof window === "undefined" || typeof navigator === "undefined") {
    // 非浏览器环境（如 Node.js 服务端）
    return "unknown";
  }

  const userAgent = navigator.userAgent.toLowerCase();

  // 移动端系统判断
  if (/iphone|ipad|ipod/.test(userAgent)) {
    return "ios";
  }
  if (/android/.test(userAgent)) {
    return "android";
  }

  // 其他设备（如 PC 浏览器）
  return "web";
}

/**
 * Web 端没有直接获取设备硬件 ID 的 API（出于隐私保护），通常通过组合浏览器特征生成唯一标识（设备指纹）
 */
function getWebDeviceId() {
  // 存储浏览器特征的对象
  const features = {};

  // 1. 硬件特征（如果支持）
  if (navigator.hardwareConcurrency) {
    features.cpuCores = navigator.hardwareConcurrency; // CPU核心数
  }
  if (window.screen) {
    features.screenSize = `${window.screen.width}x${window.screen.height}`; // 屏幕分辨率
    features.colorDepth = window.screen.colorDepth; // 颜色深度
  }

  // 2. 浏览器特征
  features.userAgent = navigator.userAgent; // 用户代理
  features.language = navigator.language; // 浏览器语言
  features.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone; // 时区

  // 3. 浏览器API支持（Canvas指纹、WebGL指纹等）
  try {
    // Canvas指纹（即使像素相同，不同设备渲染的Canvas像素数据可能有细微差异）
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    ctx.font = "16px Arial";
    ctx.fillText("DeviceIdTest", 20, 20);
    features.canvasFingerprint = canvas.toDataURL().substring(21, 30); // 截取部分数据URL作为指纹
  } catch (e) {
    features.canvasFingerprint = "error";
  }

  // 4. 存储特征（如果支持）
  try {
    // 尝试使用localStorage存储生成的ID（如果已存在则复用）
    const storedId = localStorage.getItem("deviceId");
    if (storedId) {
      return storedId;
    }
  } catch (e) {
    // 浏览器禁用了localStorage（如隐私模式）
  }

  // 5. 生成最终ID
  const featureString = Object.values(features).join("|");

  return featureString;
}

/**
 * 将扁平结构数组转换为树形层级结构
 */
function buildTree(items, idField = "menuId", parentIdField = "parentId") {
  // 创建 ID 到节点的映射（浅拷贝保留原始对象）
  const nodeMap = new Map();
  items.forEach((item) => nodeMap.set(item[idField], { ...item, children: [] }));

  // 收集所有父节点 ID
  const parentIds = new Set(items.map((item) => item[parentIdField]));

  // 构建树形结构
  const tree = [];

  items.forEach((item) => {
    const currentId = item[idField];
    const parentId = item[parentIdField];

    // 从映射中获取当前节点和父节点
    const currentNode = nodeMap.get(currentId) || { ...item, children: [] };
    const parentNode = nodeMap.get(parentId);

    // 如果父节点不存在或父节点是自身，则作为根节点
    if (parentId === undefined || parentId === null || parentId === currentId || !parentNode) {
      tree.push(currentNode);
    } else {
      // 确保父节点有 children 数组
      if (!parentNode.children) {
        parentNode.children = [];
      }
      // 将当前节点添加到父节点的 children 中
      parentNode.children.push(currentNode);
    }
  });

  return tree;
}

/**
 * 递归排序树形结构的所有节点（直接修改原数据）
 * @param {Array} tree - 树形结构数据
 * @param {Object} [options] - 配置选项
 * @param {string} [options.sortField='orderNum'] - 排序字段名
 * @param {string} [options.sortOrder='ASC'] - 排序方式 (ASC/DESC)
 * @param {string} [options.childrenField='children'] - 子节点字段名
 */
function sortTree(tree, options = {}) {
  // 解析配置参数（带默认值）
  const { sortField = "orderNum", sortOrder = "ASC", childrenField = "children" } = options;

  // 确保输入是数组
  if (!Array.isArray(tree)) return;

  // 1. 排序当前层级节点（原地排序）
  tree.sort((a, b) => {
    const aVal = a[sortField];
    const bVal = b[sortField];
    const isAsc = sortOrder.toUpperCase() === "ASC";

    // 处理字段缺失情况（缺失字段排最后）
    if (aVal === undefined && bVal === undefined) return 0;
    if (aVal === undefined) return 1;
    if (bVal === undefined) return -1;

    // 数值比较
    return isAsc ? aVal - bVal : bVal - aVal;
  });

  // 2. 递归排序所有子节点
  tree.forEach((node) => {
    if (node[childrenField] && Array.isArray(node[childrenField])) {
      sortTree(node[childrenField], options);
    }
  });
}

export {
  downloadBlob,
  deepEqual,
  deepCopy,
  encodeHTML,
  decodeHTML,
  isTimeInRange,
  getWeekRange,
  getWeek,
  fullscreen,
  exitFullscreen,
  getDescendantProp,
  getFileBase64,
  travalNode,
  findNodeInTree,
  getUrlParams,
  getUrlHash,
  filterQueryEmptyValue,
  getFileSie,
  downloadBase64File,
  transBase64DataToBlob,
  transBase64DataToFile,
  Quene,
  merge,
  getValueType,
  isFunction,
  isUndefined,
  isString,
  isNumber,
  isArray,
  isPlainObject,
  resolveQueryUrl,
  filterEmptyParams,
  getMatchItem,
  minuteToDayHours,
  getScreenDPI,
  getPaperPixels,
  substrPolyfill,
  parseTime,
  printElement,
  convertCssObjectsToStyleText,
  removeAttributesFromHtml,
  FilteringEmptyDataByZero,
  calculateTimeDuration,
  getDateTimeRange,
  isSameArray,
  convertToCamelCase,
  getNearYears,
  cloneElementToFragment,
  getPlatForm,
  getCurrentEnv,
  getWebDeviceId,
  buildTree,
  sortTree,
  getValueByPath
};
