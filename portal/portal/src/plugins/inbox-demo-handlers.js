import { registerNewMessageHandler } from "@jlkj/message-inbox/vue3";

export async function handleInboxDemoItemClick({ router, message }) {
  if (message.templateCode === "FUSION_TEST_DETAIL") {
    await router.push({ name: "TemplateComplexList" });
    return;
  }

  await router.push({ name: "TemplateStandardList" });
}

export function registerInboxDemoHandlers({ router, client }) {
  registerNewMessageHandler("FUSION_TEST_ALERT", ({ message, defaultToast }) => ({
    ...defaultToast,
    title: message.title || "模板应用测试",
    content: message.content || "模板应用测试消息",
    actions: [
      {
        key: "mark-read",
        text: "标记已读",
        type: "default",
        closeOnClick: true,
        handler: () => client.markRead(message.id)
      },
      {
        key: "open-standard-list",
        text: "打开列表模板",
        type: "primary",
        closeOnClick: true,
        handler: async () => {
          await client.markRead(message.id);
          await handleInboxDemoItemClick({ router, message });
        }
      }
    ]
  }));

  registerNewMessageHandler("FUSION_TEST_DETAIL", ({ message, defaultToast }) => ({
    ...defaultToast,
    title: message.title || "模板详情测试",
    content: message.content || "跳转到复杂列表模板",
    actions: [
      {
        key: "open-complex-list",
        text: "打开复杂列表",
        type: "primary",
        closeOnClick: true,
        handler: async () => {
          await client.markRead(message.id);
          await handleInboxDemoItemClick({ router, message });
        }
      },
      {
        key: "open-business-dashboard",
        text: "打开数据看板",
        type: "default",
        closeOnClick: true,
        handler: async () => {
          await client.markRead(message.id);
          await router.push({ name: "BusinessDashboard" });
        }
      }
    ]
  }));
}
