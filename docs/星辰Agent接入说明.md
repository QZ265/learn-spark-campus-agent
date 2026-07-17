# 讯飞星辰 Agent 接入说明

项目使用讯飞星辰工作流 HTTP API，不用固定名称在本地模拟 Agent。应用只在星辰接口真实返回成功时标记为 `astron`；未配置或调用失败时会明确显示 `spark_fallback` 或 `failed`。

## 1. 在星辰创建工作流

1. 登录讯飞星辰 Agent 平台，新建一个工作流应用。
2. 在开始节点添加字符串参数：`TASK`、`AGENT_USER_INPUT`、`STUDENT_MESSAGE`、`PROFILE_JSON`、`KNOWLEDGE_JSON`、`RESOURCE_JSON`、`RESOURCE_TYPE`、`CITATIONS_JSON`。
3. 按 `TASK` 增加条件分支：`profile`、`resource`、`review`。
4. 在三个分支分别创建并配置 `ProfileAgent`、`ResourceAgent`、`ReviewAgent` 大模型节点。
5. 每个分支的最终输出都连接到结束节点，并只输出 JSON 文本。
6. 调试三个分支后发布工作流 API。未发布的草稿不能从本项目调用。

推荐职责：

- `ProfileAgent`：从学生原话和历史画像中抽取有直接证据的画像更新 JSON。
- `ResourceAgent`：根据画像、知识库片段和合法引用生成五类资源 JSON。
- `ReviewAgent`：核对引用、事实支持关系和代码安全，返回审核 JSON。

工作流也可以将三个节点串成完整链路，但必须保留 `TASK` 分支，使画像抽取、资源生成和审核能被项目分别重试和记录。

## 2. 获取 Flow ID 与鉴权信息

发布工作流后，在 API 调用页复制工作流的 `flow_id`，填入本项目的 `ASTRON_AGENT_ID`。

工作流接口使用 Bearer 鉴权，格式为：

```text
Authorization: Bearer APIKey:APISecret
```

本项目支持两种配置方式：

```text
ASTRON_API_KEY=APIKey:APISecret
ASTRON_AGENT_ID=工作流flow_id
```

或分开填写：

```text
ASTRON_API_KEY=APIKey
ASTRON_API_SECRET=APISecret
ASTRON_AGENT_ID=工作流flow_id
```

不要把密钥写进 `app.py`、前端 JavaScript 或提交到公开仓库。

## 3. 项目配置与启动

打开根目录的 `config_keys.env`，填写上述变量，然后完全重启服务：

```bash
./START_SERVER_MAC_LINUX.sh
```

健康检查地址为 `http://127.0.0.1:8000/api/health`。其中 `astron_configured` 为 `true` 只表示环境变量完整；实际响应中的 `profile_agent`、`agent_mode` 才表示本次是否真实调用成功。

## 4. 项目调用方式

客户端实现位于 `services/astron_agent_client.py`，调用官方接口：

```text
POST https://xingchen-api.xf-yun.com/workflow/v1/chat/completions
```

请求体包含 `flow_id`、`uid`、`parameters` 和 `stream: false`。客户端负责超时、指数退避重试、错误日志和调用状态区分。星辰不可用时，服务层可以转到 Spark X，但响应会标记为 `spark_fallback`，不会假装是星辰结果。

## 5. 常见错误

- `401/鉴权失败`：APIKey 与 APISecret 不属于同一应用，或 Bearer 值缺少冒号。
- `flow_id 无效`：填入了节点 ID、应用名或草稿 ID；应复制发布后的工作流 ID。
- `参数不存在`：工作流开始节点没有创建本项目发送的参数名，注意大小写一致。
- `返回内容为空`：结束节点没有绑定模型节点输出，或输出不是文本。
- `超时`：检查工作流中的循环、知识检索和模型节点；可调整 `ASTRON_TIMEOUT_SECONDS`。
- 一直显示 `spark_fallback`：查看服务日志中的 `pylearn.astron` 错误，并先确认 `/api/health` 的配置状态。

## 6. 官方资料

- [星辰工作流 API 文档](https://www.xfyun.cn/doc/spark/workflow.html)
- [星辰 Agent 开发指南](https://www.xfyun.cn/doc/spark/Agent03-%E5%BC%80%E5%8F%91%E6%8C%87%E5%8D%97.html)
- [星辰 Agent 快速开始](https://www.xfyun.cn/doc/spark/Agent02-%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B.html)
