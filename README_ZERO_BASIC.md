# PyLearnSpark A3 Voice Final 零基础运行说明

这是软件杯 A3 第三题“Python课程普惠智能体”比赛演示版。

本版本包含：

- Web 网页端
- FastAPI 本地服务器
- 讯飞星火大模型聊天接口
- 讯飞语音识别接口：麦克风说话 -> 转文字 -> 发给智能体
- 讯飞星辰 Workflow：ProfileAgent、ResourceAgent、ReviewAgent
- 基于证据的九字段动态学生画像
- Python 课程知识库检索与官方来源引用
- 五类真实学习资源生成、SQLite 保存和独立打开页面
- ReviewAgent 引用审核、代码检查和失败重生

---

## 一、最稳运行步骤 Windows

### 第 1 步：一定先解压

不要在压缩包里面双击文件。

正确操作：

1. 右键 `A3_PyLearnSpark_Voice_Final.zip`
2. 选择“全部解压缩”
3. 进入解压后的 `A3_PyLearnSpark_Voice_Final` 文件夹

### 第 2 步：启动服务器

双击：

```text
START_SERVER_WINDOWS.bat
```

黑色窗口不要关。

成功后浏览器会打开：

```text
http://127.0.0.1:8000
```

聊天页面是：

```text
http://127.0.0.1:8000/chat
```

---

## 二、黑框一闪而过怎么办

本版本理论上不会闪退，因为脚本最后有 pause。

如果还是闪退，先双击：

```text
CHECK_ENVIRONMENT.bat
```

看电脑有没有 Python。

如果没有 Python：

1. 打开浏览器
2. 搜索 Python 官网
3. 下载 Python 3.10 或更高版本
4. 安装时一定勾选：Add python.exe to PATH
5. 重新双击 `START_SERVER_WINDOWS.bat`

如果启动失败，本文件夹会生成：

```text
server_start_log.txt
```

把里面内容复制给 ChatGPT，就能定位错误。

---

## 三、不接星火也能不能演示

网页和本地知识库答疑可以打开，但动态画像结构化抽取、真实资源生成和 ReviewAgent 审核需要至少配置 Spark X 或讯飞星辰。未配置时接口会明确返回失败状态，不会用假数据冒充成功。

只想先看页面，可以双击：

```text
OPEN_DEMO_NO_SERVER.html
```

这个文件只用于查看静态入口，不包含真实接口和比赛功能。正式演示必须启动服务器。

---

## 四、接入真实讯飞星火大模型

打开：

```text
config_keys.env
```

找到这一行：

```text
SPARK_API_PASSWORD=
```

在等号后面填你的 APIPassword。

例子：

```text
SPARK_API_PASSWORD=xxxxxxxxxxxxxxxx
```

保存文件，重新双击：

```text
START_SERVER_WINDOWS.bat
```

然后在网页右上角选择 Spark X 大模型模式。

---

## 五、接入真实语音识别

语音识别需要三项：

```text
XF_ASR_APP_ID=
XF_ASR_API_KEY=
XF_ASR_API_SECRET=
```

打开 `config_keys.env`，填到等号后面。

保存后重启服务器。

然后进入聊天页面，点击麦克风按钮：

1. 第一次浏览器会问你是否允许使用麦克风，选择允许。
2. 对着麦克风说一句 Python 学习问题。
3. 再点一次按钮停止录音。
4. 系统会把识别文字填入输入框。
5. 你可以修改后点击发送。

注意：语音识别必须从服务器页面打开，也就是：

```text
http://127.0.0.1:8000/chat
```

不能只打开本地 HTML 文件。

---

## 六、星辰 Agent 配置

请阅读 `docs/星辰Agent接入说明.md`。只有配置并发布真实星辰 Workflow 后，页面调用状态才会显示 `astron`；否则会明确显示 `spark_fallback` 或 `failed`。

---

## 七、文件说明

```text
START_SERVER_WINDOWS.bat        Windows 一键启动正式版
START_SERVER_NO_VENV.bat        备用启动方式
CHECK_ENVIRONMENT.bat           检查 Python 是否安装
OPEN_DEMO_NO_SERVER.html        不启动服务器的静态演示页
config_keys.env                 填星火和语音识别密钥的地方
app.py                          后端服务器与多智能体逻辑
static/                         网页文件
static/chat.html                聊天页面，含语音输入按钮
static/chat.js                  录音、语音识别、聊天交互逻辑
static/profile.html             证据驱动的动态画像页面
static/resource.html            已保存学习资源的打开页面
data/knowledge_base.json        Python 课程知识库
data/citations.json             官方来源引用
data/app.db                     画像和资源 SQLite 数据库
services/astron_agent_client.py 星辰 Workflow 客户端
requirements.txt                Python 依赖
```

---

## 八、提交注意

不要把真实密钥上传到公开仓库。

比赛提交可以保留空的 `config_keys.env`，现场演示时在自己电脑上填真实密钥。
