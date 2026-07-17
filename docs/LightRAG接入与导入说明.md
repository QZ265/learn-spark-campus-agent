# LightRAG 接入与导入说明

## 锁定版本与运行方式

- LightRAG：`lightrag-hku==1.5.4`（PyPI 当前稳定版，未使用 RC、main 或 latest）
- Python：3.10 以上；本机项目环境为 `.venv-lightrag` / Python 3.12
- Embedding：`BAAI/bge-small-zh-v1.5`，512 维，最大 512 tokens，批量 16
- 向量与图存储：LightRAG 默认 NanoVectorDB + NetworkX 文件存储
- Reranker：未配置，系统明确显示为关闭
- Web 框架：仓库现状实际为 FastAPI，继续复用现有 `app.py`，没有改写为 Flask

官方依据：

- GitHub：https://github.com/HKUDS/LightRAG
- PyPI：https://pypi.org/project/lightrag-hku/1.5.4/

为降低现场依赖和模型调用成本，默认使用 LightRAG 官方 `!F` 处理选项：固定分块、真实 Embedding、跳过知识图谱抽取。设置 `LIGHTRAG_ENABLE_KG=true` 后才会调用 Spark X 做真实实体关系抽取。

## 启动

```bash
cd "/Users/dhang/Documents/SOFTWARE_CUP/A3_PyLearnSpark_Voice_Final 2"
./START_SERVER_MAC_LINUX.sh
```

访问：

- 首页：http://127.0.0.1:8000/
- 答疑：http://127.0.0.1:8000/chat
- 课程助手：http://127.0.0.1:8000/assistants

## 教材扫描

扫描只生成清单，不自动索引分类不确定、重复、不可解析或需要 OCR 的文件。

```bash
.venv-lightrag/bin/python scripts/scan_course_materials.py \
  --root "/Users/dhang/Documents/rag"
```

输出：

- `data/course_material_inventory.csv`
- `data/course_material_manifest.json`

扫描 PDF 没有文本层时会标记 `needs_ocr=true`。本机 macOS 使用 `PyMuPDF + macOS Vision` 做真实中文 OCR；其他系统没有安装对应 OCR 引擎时会明确失败，不会假装导入成功。

## 增量导入

先预览：

```bash
.venv-lightrag/bin/python scripts/import_course_materials.py \
  --dry-run --course programming_python --limit 1
```

实际导入：

```bash
.venv-lightrag/bin/python scripts/import_course_materials.py \
  --course programming_python --limit 1 --workers 2
```

恢复和重试：

```bash
.venv-lightrag/bin/python scripts/import_course_materials.py --resume
.venv-lightrag/bin/python scripts/import_course_materials.py --retry-failed
```

其他参数：`--domain`、`--document-id`、`--force-reindex`、`--skip-duplicates`、`--no-skip-duplicates`、`--sync-deletions`。

每个文件先计算 SHA256；同一 workspace 中的重复哈希会建立状态为 `duplicate` 的真实任务记录，不会重复写入索引。不同 workspace 使用包含 workspace 的文档 ID，所以同一教材放入不同用户助手时不会撞库。

## 课程隔离

公共课程 workspace：

- `programming_python`
- `math_calculus`
- `math_linear_algebra`
- `math_probability_statistics`
- `politics_maogai`
- `politics_modern_history`
- `politics_xi_thought`

用户助手 workspace 格式为 `user_<user_id>_<assistant_id>`。API 会同时校验 `assistant_id` 所属用户、`course_id` 与 workspace，检索结果再次校验引用的课程和 workspace。

## 环境变量

现有 Spark X、星辰 Workflow 和语音密钥继续放在 `.env` 或 `config_keys.env`，不要写入代码。LightRAG 可选项：

```text
LIGHTRAG_WORKING_DIR=data/lightrag
LIGHTRAG_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
LIGHTRAG_EMBEDDING_DIM=512
LIGHTRAG_EMBEDDING_MAX_TOKENS=512
LIGHTRAG_EMBEDDING_BATCH_SIZE=16
LIGHTRAG_MIN_RELEVANCE=0.45
LIGHTRAG_ENABLE_KG=false
INDEXING_WORKERS=2
```

修改 Embedding 模型或维度后必须对已有 workspace 执行重新索引，不能混用不同维度的向量文件。
