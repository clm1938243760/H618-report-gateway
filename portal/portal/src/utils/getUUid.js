import { v4 as uuidv4 } from "uuid";
import setting from "@/setting";

// 生成一个游客id
export const getAnonymousID = () => {
  let uuid_token = sessionStorage.getItem(setting.appNameSpace + ".UUIDTOKEN");
  if (!uuid_token) {
    uuid_token = uuidv4();
    sessionStorage.setItem(setting.appNameSpace + ".UUIDTOKEN", uuid_token);
  }
  //切记有返回值
  return uuid_token;
};

export const getUUid = () => {
  return uuidv4();
};
