import request from "@/utils/request";
import qs from "qs";

/*******************    诊区相关    *******************/

// 新增诊区
export function diagnosisAreaAdd(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/diagnosisArea/add",
    data,
    method: "post",
    ...config
  });
}

// 诊区: 批量删除
export function diagnosisAreaBatchDelete(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/diagnosisArea/batchDelete",
    data,
    method: "post",
    ...config
  });
}

// 诊区: 单个删除
export function diagnosisAreaDelete(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/diagnosisArea/delete",
    data,
    method: "post",
    ...config
  });
}

// 获取所有诊区
export function diagnosisAreaGetAll(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/diagnosisArea/getAll?" + qs.stringify(data),
    data,
    method: "get",
    ...config
  });
}

// 诊区: 分页查询
export function diagnosisAreaPage(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/diagnosisArea/page",
    data,
    method: "post",
    ...config
  });
}

// 诊区: 编辑
export function diagnosisAreaUpdate(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/diagnosisArea/update",
    data,
    method: "post",
    ...config
  });
}

/*******************    分组相关    *******************/

// 分组: 新增
export function groupAdd(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/group/add",
    data,
    method: "post",
    ...config
  });
}

// 分组: 删除
export function groupDelete(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/group/delete",
    data,
    method: "post",
    ...config
  });
}

// 分组: 查询所有分组
export function groupGetAll(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/group/getAll?" + qs.stringify(data),
    data,
    method: "get",
    ...config
  });
}

// 分组: 分页查询
export function groupPage(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/group/page",
    data,
    method: "post",
    ...config
  });
}

// 分组: 修改分组
export function groupUpdate(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/group/update",
    data,
    method: "post",
    ...config
  });
}

/*******************    检查方法(方式)相关    *******************/

// 方法: 新增
export function methodAdd(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/method/add",
    data,
    method: "post",
    ...config
  });
}

// 方法: 新增
export function methodDelete(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/method/delete",
    data,
    method: "post",
    ...config
  });
}

// 方法: 查询所有方法
export function methodGetAll(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/method/getAll?" + qs.stringify(data),
    data,
    method: "get",
    ...config
  });
}

// 方法: 分页查询
export function methodPage(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/method/page",
    data,
    method: "post",
    ...config
  });
}

// 方法: 修改方法
export function methodUpdate(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/method/update",
    data,
    method: "post",
    ...config
  });
}

/*******************    检查类型相关    *******************/

// 类别: 新增
export function modalityAdd(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/modality/add",
    data,
    method: "post",
    ...config
  });
}

// 类别: 删除
export function modalityDelete(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/modality/delete",
    data,
    method: "post",
    ...config
  });
}

// 类别: 获取所有类别
export function modalityGetAll(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/modality/getAll?" + qs.stringify(data),
    method: "get",
    ...config
  });
}

// 类别: 分页查询
export function modalityPage(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/modality/page",
    data,
    method: "post",
    ...config
  });
}

// 类别: 分页查询
export function modalityUpdate(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/modality/update",
    data,
    method: "post",
    ...config
  });
}

/*******************    部位相关    *******************/

// 部位: 新增
export function partAdd(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/part/add",
    data,
    method: "post",
    ...config
  });
}

// 部位: 分页查询
export function partPage(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/part/page",
    data,
    method: "post",
    ...config
  });
}

// 部位: 获取所有部位
export function partGetAll() {
  return request({
    url: "/yjstation/api/v1/dock/part/getAll",
    method: "get"
  });
}

// 部位: 更新
export function partUpdate(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/part/update",
    data,
    method: "post",
    ...config
  });
}

// 部位: 删除
export function partDelete(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/part/delete",
    data,
    method: "post",
    ...config
  });
}

/*******************    诊室相关    *******************/

// 诊室: 新增
export function consultingRoomAdd(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/room/add",
    data,
    method: "post",
    ...config
  });
}

// 诊室: 获取所有诊室
export function consultingRoomGetAll() {
  return request({
    url: "/yjstation/api/v1/dock/room/getAll",
    method: "get"
  });
}

// 诊室: 更新
export function consultingRoomUpdate(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/room/update",
    data,
    method: "post",
    ...config
  });
}

// 诊室: 删除
export function consultingRoomDelete(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/room/delete",
    data,
    method: "post",
    ...config
  });
}

// 诊室: 分页查询
export function consultingRoomPage(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/room/page",
    data,
    method: "post",
    ...config
  });
}

/*******************    检查项目相关    *******************/

// 检查项目: 新增
export function projectAdd(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/project/add",
    data,
    method: "post",
    ...config
  });
}

// 检查项目: 分页查询
export function projectPage(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/project/page",
    data,
    method: "post",
    ...config
  });
}

// 检查项目: 更新
export function projectUpdate(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/project/update",
    data,
    method: "post",
    ...config
  });
}

// 检查项目: 删除
export function projectDelete(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/project/delete",
    data,
    method: "post",
    ...config
  });
}

// 检查项目: 批量删除
export function projectBatchDelete(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/project/batchDelete",
    data,
    method: "post",
    ...config
  });
}

// 检查项目: 获取所有检查项目
export function projectGetAll(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/project/getAll?" + qs.stringify(data),
    method: "get",
    ...config
  });
}

/*******************    检查设备相关    *******************/

// 检查设备: 新增
export function deviceAdd(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/device/add",
    data,
    method: "post",
    ...config
  });
}

// 检查设备: 分页查询
export function devicePage(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/device/page",
    data,
    method: "post",
    ...config
  });
}

// 检查设备: 修改
export function deviceUpdate(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/device/update",
    data,
    method: "post",
    ...config
  });
}

// 检查设备: 删除
export function deviceDelete(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/device/delete",
    data,
    method: "post",
    ...config
  });
}

// 检查设备: 获取所有检查设备
export function deviceGetAll(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/device/getAll",
    method: "get",
    ...config
  });
}

/*******************    工作站相关    *******************/
// 工作站: 新增
export function workstationAdd(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/workstation/add",
    data,
    method: "post",
    ...config
  });
}

// 工作站: 分页查询
export function workstationPage(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/workstation/page",
    data,
    method: "post",
    ...config
  });
}

// 工作站: 获取所有工作站
export function workstationGetAll(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/workstation/getAll",
    method: "get",
    ...config
  });
}

// 工作站: 删除
export function workstationDelete(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/workstation/delete",
    data,
    method: "post",
    ...config
  });
}

// 工作站: 修改
export function workstationUpdate(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/workstation/update",
    data,
    method: "post",
    ...config
  });
}

/*******************    药品相关    *******************/
// 药品: 新增
export function drugAdd(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/drug/add",
    data,
    method: "post",
    ...config
  });
}

// 药品: 删除
export function drugDelete(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/drug/delete",
    data,
    method: "post",
    ...config
  });
}

// 药品: 获取所有
export function drugAll(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/drug/getAll",
    data,
    method: "get",
    ...config
  });
}

// 药品: 分页
export function drugPage(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/drug/page",
    data,
    method: "post",
    ...config
  });
}

// 药品: 修改
export function drugUpdate(data, config = {}) {
  return request({
    url: "/yjstation/api/v1/dock/drug/update",
    data,
    method: "post",
    ...config
  });
}
