import XLSX from "xlsx";
import { cloneDeep } from "lodash";
import { ElMessage } from "element-plus";
import { isPlainObject, isArray, isFunction } from "./tool";

/**
 * xlsx 导出表格辅助函数
 * columnHeaders 表头信息
 * data 数据
 * cellStyle 列宽度
 * cellMerge 合并单元格设置
 * fileName 导出文件名
 * isGruopColumn 是否是多层级表头
 */
// eslint-disable-next-line default-param-last
function exportExcel(columnHeaders, data, cellStyle, cellMerge = [], fileName, isGruopColumn) {
  function outputXlsxFile(data, wscols, xlsxName) {
    // 用于生成并保存 Excel 文件
    const sheetNames = []; // 存储 sheet 名称
    const sheetsList = {}; // 存储所有 sheet 的数据
    const wb = XLSX.utils.book_new(); // 创建了一个新的工作簿对象 wb

    for (const key in data) {
      sheetNames.push(key);
      const columnHeader = columnHeaders[key]; // 获取当前 sheet 对应的列头信息 columnHeader
      const temp = transferData(data[key], columnHeader, isGruopColumn);
      sheetsList[key] = XLSX.utils.aoa_to_sheet(temp); // 创建 sheet 对象
      sheetsList[key]["!cols"] = wscols; // 当前 sheet 设置列宽 wscols
      sheetsList[key]["!merges"] = cellMerge; // 当前 sheet 设置列宽 wscols
    }

    wb.SheetNames = sheetNames;
    wb.Sheets = sheetsList;
    XLSX.writeFile(wb, `${xlsxName}.xlsx`); // 将工作簿保存为 Excel 文件
  }

  // 将列字母（如'A'）转换为数字索引（0开始）
  function colToIndex(col) {
    let index = 0;
    for (let i = 0; i < col.length; i++) {
      const c = col.charCodeAt(i) - 65; // 'A' -> 0, 'B' -> 1, 等
      index = index * 26 + c;
    }
    return index;
  }

  function transferData(data, columnHeader, isGruopColumn) {
    // 将数据按照列头信息进行转换，将每一行的数据转换成一个数组
    const content = [];
    if (isGruopColumn) {
      content.push(...columnHeader);
    } else {
      content.push(columnHeader);
    }

    data.forEach((item, index) => {
      const arr = []; // 用于存储当前行的数据

      if (isGruopColumn) {
        columnHeader[columnHeader.length - 1].forEach((column, index) => {
          arr.push(item[index]); // 使用 map 方法遍历 columnHeader，将每个列头对应的属性值添加到 arr 数组中
        });
      } else {
        columnHeader.forEach((column) => {
          arr.push(isPlainObject(item) ? item[column] : item); // 使用 map 方法遍历 columnHeader，将每个列头对应的属性值添加到 arr 数组中
        });
      }

      content.push(arr); // 将 arr 数组添加到 content 数组中
    });

    return content;
  }
  outputXlsxFile(data, cellStyle, fileName);
}

/**
 * 通用导出方法: 通过调用列表接口, 下载 excel
 * @param {Promise} api 调用的列表接口
 * @param {Any} payload 调用 api 时传入的参数
 * @param {Function | null} responseFormat 接口返回值预处理函数
 * @param {Array} exportColumn 要导出的扁平结构的列, 一般使用该字段
 * @param {Object} groupedExportColumn 树结构的, 带层级结构的列。如果是二级表头的使用该字段
 * @param {String} columnChildrenKey 当使用了树结构的列, 可能需要指定子节点读取的 key, 默认为 children
 * @param {String} sheetName 导出的表格工作表名称
 * @param {String} fileName 导出的文件名名称, 无需再定义后缀
 */
function downloadExcelWithApi({
  api /* 列表接口 */,
  payload /* 查询参数 */,
  responseFormat /* 响应值处理函数 */,
  exportColumn /* 导出列 */,
  groupedExportColumn /* 带分组的导出列 */,
  columnChildrenKey /* 分组列子项的 key */,
  sheetName /* 工作表名称 */,
  fileName /* 导出文件名 */
}) {
  const exportHeaders = [];
  const exportHeadersWidth = [];

  // 扁平结构表格头
  if (exportColumn) {
    exportColumn.forEach((item) => {
      exportHeaders.push(item.label);
      exportHeadersWidth.push({ wch: (item.width || item.minWidth || 80) / 6 });
    });
  }

  let headerData;
  let colMerges;
  let colWidthSetting;
  // 分组层级结构表格头
  if (groupedExportColumn) {
    const { rows, merges, colWidths } = buildComplexHeader(groupedExportColumn, columnChildrenKey || "children");
    headerData = rows;
    colMerges = merges;
    colWidthSetting = colWidths;
  }

  api(payload)
    .then((res) => {
      if (res.code !== 200) {
        ElMessage.error("导出失败");
      } else {
        const data = res.data;
        let exportData = [];
        if (isArray(data)) {
          const preprocessingData = isFunction(responseFormat) ? responseFormat(data) : data;
          exportData = getExportData(preprocessingData, groupedExportColumn || exportColumn, !!groupedExportColumn, columnChildrenKey || "children");
        } else if (isPlainObject(data)) {
          const records = data.records;
          const preprocessingData = isFunction(responseFormat) ? responseFormat(records) : records;
          if (isArray(records)) {
            exportData = getExportData(
              preprocessingData,
              groupedExportColumn || exportColumn,
              !!groupedExportColumn,
              columnChildrenKey || "children"
            );
          }
        }

        ElMessage.success("导出成功");

        exportExcel(
          {
            [sheetName || fileName]: groupedExportColumn ? headerData : exportHeaders
          },
          {
            [sheetName || fileName]: exportData
          },
          groupedExportColumn ? colWidthSetting : exportHeadersWidth,
          colMerges,
          fileName,
          !!groupedExportColumn
        );
      }
    })
    .catch((e) => {
      ElMessage.error("导出失败");
    });
}

/**
 * 获取表格数据: 值转换
 * @param {Array} tableData 预处理之后的表格数据
 * @param {Array} exportHeaders 要导出的表格头
 * @param {Boolean} isGruopColumn 是否是分组表格头, 分组的表格头会递归处理层级
 * @param {String} childrenKey 如果是分组表格头, 对应自定义子项的 key
 * @returns {Array} 返回工作簿数据
 */
function getExportData(tableData, exportHeaders, isGruopColumn, childrenKey = "children") {
  const res = [];
  tableData.forEach((row) => {
    let excelData;
    if (isGruopColumn) {
      excelData = [];

      traverseHeader(exportHeaders, childrenKey, (node, parent, level) => {
        if (parent) {
          // 中间层级节点, 不处理
        } else {
          const { prop, label, formatter, dict } = node;

          let value;
          if (prop) {
            if (typeof formatter === "function") {
              value = formatter(row[prop], row, node);
            } else if (dict) {
              value = dict[row[prop]];
            } else {
              value = row[prop];
            }
            excelData.push(value);
          } else if (node[childrenKey]) {
            traverseHeader(node[childrenKey], childrenKey, (node, parent, level) => {
              const { prop, label, formatter, dict } = node;

              let value;
              if (prop) {
                if (typeof formatter === "function") {
                  value = formatter(row[prop], row, node);
                } else if (dict) {
                  value = dict[row[prop]];
                } else {
                  value = row[prop];
                }
                excelData.push(value);
              }
            });
          }
        }
      });
    } else {
      excelData = {};
      exportHeaders.forEach((item, index) => {
        const { prop, label, formatter, dict } = item;

        if (typeof formatter === "function") {
          excelData[label] = formatter(row[prop], row, item);
        } else if (dict) {
          excelData[label] = dict[row[prop]];
        } else {
          excelData[label] = row[prop];
        }
      });
    }

    res.push(excelData);
  });

  return res;
}

/**
 * 构建多层级表头结构
 * @param {Array} config 表头配置（需提前通过 initColspan 初始化）
 * @param {String} childrenKey 子节点字段名（默认 'children'）
 * @returns {Object} { rows: 二维表头数据, merges: 合并配置, colWidths: 列宽配置 }
 */
function buildComplexHeader(config, childrenKey = "children") {
  const rows = []; // 二维表头数据（每一行对应一个层级的表头）
  const merges = []; // 合并单元格配置
  const colWidths = []; // 列宽配置（每个索引对应列）
  let maxDepth = 0; // 记录最大层级深度

  // 第一步：计算最大深度，初始化 rows 数组
  const calculateDepth = (nodes, currentDepth) => {
    nodes.forEach((node) => {
      maxDepth = Math.max(maxDepth, currentDepth);
      if (node[childrenKey]) {
        calculateDepth(node[childrenKey], currentDepth + 1);
      }
    });
  };
  calculateDepth(config, 1); // 从第1层开始（0-based）
  for (let i = 0; i < maxDepth; i++) rows.push([]);

  // 第二步：递归填充表头数据和计算合并范围
  const processNode = (node, depth, startCol, parentStartCol, parentSpan) => {
    const currentRow = rows[depth];
    const isLeaf = !node[childrenKey];

    // 填充当前层级的标签（处理跨列情况）
    if (isLeaf) {
      // 叶子节点：直接填充标签，并设置列宽
      currentRow[startCol] = node.label;
      colWidths[startCol] = { wch: node.width || 15 };
    } else {
      // 分组节点：填充标签，并递归处理子节点
      currentRow[startCol] = node.label;
      let childStartCol = startCol;
      node[childrenKey].forEach((child) => {
        const childSpan = processNode(child, depth + 1, childStartCol, startCol, node.colspan);
        childStartCol += childSpan;
      });
    }

    // 记录合并范围（非叶子节点且跨列数>1）
    if (!isLeaf && node.colspan > 1) {
      merges.push({
        s: { r: depth, c: startCol },
        e: { r: depth, c: startCol + node.colspan - 1 }
      });
    }

    // 返回当前节点的跨列数（用于父级调整位置）
    return node.colspan;
  };

  // 从根节点开始处理（深度从0开始）
  let currentCol = 0;
  config.forEach((rootNode) => {
    const span = processNode(rootNode, 0, currentCol, 0, 0);
    currentCol += span;
  });

  // 第三步：填充空位置（确保二维数组的完整性）
  rows.forEach((row, depth) => {
    for (let i = 0; i < currentCol; i++) {
      if (row[i] === undefined) row[i] = ""; // 空单元格填充空字符串
    }
  });

  return { rows, merges, colWidths };
}

/**
 * 自动初始化 headerConfig 中节点的 colspan 字段
 * @param {Array} config 表头配置数组
 * @returns 自动填充 colspan 的配置
 */
function initColspan(config, childrenKey = "children") {
  // 递归处理配置项
  const processNode = (node) => {
    if (node[childrenKey]) {
      // 先处理子节点
      node[childrenKey].forEach(processNode);

      // 计算当前节点的 colspan = 所有子节点 colspan 的总和
      node.colspan = node[childrenKey].reduce((sum, child) => sum + child.colspan, 0);
    } else {
      // 叶子节点默认 colspan=1
      node.colspan = 1;
    }
    return node;
  };

  // 深拷贝配置避免污染原数据
  const clonedConfig = cloneDeep(config);
  return clonedConfig.map(processNode);
}

/**
 * 深度优先遍历 headerConfig 节点
 * @param {Array} config 表头配置数组
 * @param {Function} callback 遍历到每个节点时执行的回调函数，参数格式为 (node, parent, level)
 * @param {Object} [options] 可选参数
 * @param {number} [options.level=0] 当前层级（内部递归使用，无需手动设置）
 * @param {Object} [options.parent=null] 父节点（内部递归使用，无需手动设置）
 */
function traverseHeader(config, childrenKey, callback, { level = 0, parent = null } = {}) {
  if (!Array.isArray(config)) return;

  config.forEach((node) => {
    // 执行回调函数，传递当前节点、父节点和层级
    callback(node, parent, level);

    // 递归处理子节点（深度优先）
    if (node.children) {
      traverseHeader(node.children, childrenKey, callback, {
        level: level + 1,
        parent: node
      });
    }
  });
}

export { exportExcel, downloadExcelWithApi, initColspan };
