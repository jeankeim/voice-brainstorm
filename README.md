# 灵感风暴 - AI 头脑风暴助手

一个基于 AI 的头脑风暴工具，通过**深度提问**帮助用户把模糊的想法变成清晰的方案。支持语音输入、多模态文件分析、个人知识库 RAG 检索等功能。

## ✨ 核心亮点

### 🎯 深度头脑风暴工作流
不同于普通问答，灵感风暴采用**引导式对话**：
- AI 通过连续追问，帮你梳理思路、发现盲点
- 3-5 轮对话后自动生成结构化总结
- 支持随时输出完整的想法文档（Markdown 格式）

### 🎤 多模态输入
- **语音输入**：点击麦克风直接说话，支持实时语音识别
- **图片分析**：上传图片，AI 可识别内容并基于图片进行头脑风暴
- **文档上传**：支持 PDF、TXT、Markdown、Word 文档，自动提取内容分析

### 📚 个人知识库 + RAG
- 创建多个知识库，上传领域相关文档
- **混合召回技术**：向量语义检索 + BM25 关键词检索，双重保障召回率
- 对话时自动检索知识库内容，给出更精准的建议

### 🔧 技术特色
- **双模式数据库**：SQLite 本地开发 / PostgreSQL + pgvector 生产部署
- **流式响应**：打字机效果，实时显示 AI 回复
- **访客系统**：基于浏览器指纹的访客识别，每日限额控制
- **响应式设计**：完美适配桌面和移动端

## 功能展示

| 功能 | 描述 |
|------|------|
| 💡 深度追问 | AI 像创业顾问一样，通过问题引导你完善想法 |
| 📝 自动总结 | 对话结束后生成结构化的想法文档 |
| 🎙️ 语音输入 | 支持语音识别，解放双手 |
| 📷 图片分析 | 上传产品草图、竞品截图等，AI 基于图片讨论 |
| 📄 文档解析 | 上传商业计划书、市场调研报告等 PDF/Word 文件 |
| 📚 知识库 RAG | 构建个人知识库，让 AI 基于你的资料回答 |
| 🔍 混合召回 | 向量检索 + 关键词检索，提升检索效果 |

## 技术栈

### 后端架构
| 组件 | 技术 |
|------|------|
| Web 框架 | Flask |
| 大模型 API | 阿里云 DashScope（通义千问 qwen-plus / qwen-vl-plus）|
| 向量嵌入 | DashScope text-embedding-v2 |
| 数据库 | SQLite（本地）/ PostgreSQL + pgvector（生产）|
| 向量数据库 | ChromaDB（本地）/ PostgreSQL pgvector（生产）|
| 文件存储 | Cloudflare R2（可选）|
| 语音识别 | DashScope 语音转文字 |

### 前端技术
- 原生 HTML5 / CSS3 / JavaScript（ES6+）
- 响应式布局，移动端优先
- 原生 Web Speech API 语音识别

### 核心依赖
```
flask>=3.0              # Web 框架
dashscope>=1.20.0       # 阿里云大模型 SDK
chromadb>=0.4.0         # 向量数据库（本地）
psycopg2-binary>=2.9.0  # PostgreSQL 驱动
pydub>=0.25.0           # 音频处理
PyPDF2>=3.0.0           # PDF 解析
python-docx>=0.8.11     # Word 文档解析
langchain>=0.1.0        # 文本分割
Pillow>=10.0.0          # 图片处理
```

## 快速开始

### 1. 克隆项目
```bash
git clone https://github.com/jeankeim/voice-brainstorm.git
cd voice-brainstorm
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
创建 `.env` 文件：
```env
# 必填：阿里云 DashScope API Key
DASHSCOPE_API_KEY=your_api_key_here

# 可选：R2 文件存储配置（不配置则使用本地存储）
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_BUCKET_NAME=your_bucket_name

# 可选：PostgreSQL 数据库（不配置则使用 SQLite）
DATABASE_URL=postgresql://user:password@host:port/dbname
```

### 4. 启动服务
```bash
python app.py
```

服务将在 http://127.0.0.1:5002 启动

## 部署

### Zeabur 部署
1. Fork 本项目到个人 GitHub
2. 在 Zeabur 创建新项目，选择 GitHub 仓库
3. 添加环境变量（`DASHSCOPE_API_KEY` 等）
4. 自动部署完成

### Docker 部署
```bash
docker build -t voice-brainstorm .
docker run -p 5002:5002 -e DASHSCOPE_API_KEY=xxx voice-brainstorm
```

## 项目结构

```
voice-brainstorm/
├── app.py                 # Flask 主应用
├── config.py              # 集中配置
├── database.py            # 数据库管理（SQLite/PostgreSQL）
├── knowledge_base.py      # 知识库与向量检索
├── retrieval.py           # RAG 检索逻辑
├── embedding.py           # 文本向量化
├── logger.py              # 结构化日志
├── static/
│   ├── css/style.css      # 样式文件
│   └── js/                # 前端脚本
│       ├── app.js
│       ├── session_manager.js
│       └── knowledge_base.js
├── templates/
│   └── index.html         # 主页面
└── requirements.txt       # Python 依赖
```

## 使用指南

### 首次使用
1. 打开网页后，会显示三步新手引导，介绍核心功能
2. 在欢迎页点击示例按钮，或直接输入你的想法
3. AI 会开始提问，通过 3-5 轮对话帮你完善思路
4. 随时说"总结"，AI 会输出结构化的想法文档

### 头脑风暴示例
**输入**："我想做一个帮助大学生找兼职的 APP"

**AI 追问**：
- 这个 APP 解决的核心痛点是什么？（时间灵活？收入保障？）
- 目标用户主要是哪些大学生？（大一新生？有专业技能的高年级？）
- 和现有的兼职平台相比，差异化优势在哪里？

**自动总结**：生成包含核心价值、目标用户、实施路径、潜在挑战的完整文档

### 使用知识库
1. 点击左上角 ☰ 菜单，切换到"知识库"标签
2. 创建知识库（如"创业项目"、"产品设计"）
3. 上传相关文档：商业计划书、竞品分析、市场调研报告
4. 开启 RAG 开关，AI 会自动检索文档内容回答问题

### 语音输入
1. 点击麦克风按钮 🎤 开始录音（支持 20 秒语音）
2. 直接说出你的想法，无需打字
3. 自动识别并发送给 AI

### 文件分析
- **图片**：上传产品草图、竞品截图，AI 可识别并基于图片讨论
- **PDF/Word**：上传商业计划书等文档，自动提取内容分析
- **多文件**：结合知识库上传多个文档，进行综合分析

## 配置说明

### 模型配置（config.py）
- `MODEL_TEXT`：文本模型（默认 qwen-plus）
- `MODEL_VISION`：多模态模型（默认 qwen-vl-plus）
- `MAX_TOKENS`：最大输出长度（默认 1500）
- `DAILY_LIMIT`：每日使用限制（默认 10 次）

### RAG 配置
- `vector_weight`：向量检索权重（0-1，默认 0.5）
- `chunk_size`：文档分块大小（默认 500）
- `chunk_overlap`：分块重叠大小（默认 50）

## 项目架构

```
voice-brainstorm/
├── app.py                 # Flask 主应用，API 路由
├── config.py              # 集中配置管理
├── database.py            # 数据库管理（SQLite/PostgreSQL 双模式）
├── knowledge_base.py      # 知识库与向量检索（混合召回）
├── retrieval.py           # RAG 检索逻辑
├── embedding.py           # 文本向量化（DashScope）
├── logger.py              # 结构化日志
├── static/
│   ├── css/style.css      # 样式文件
│   └── js/
│       ├── app.js                 # 主应用逻辑
│       ├── session_manager.js     # 会话管理
│       └── knowledge_base.js      # 知识库前端
├── templates/
│   └── index.html         # 主页面
├── requirements.txt       # Python 依赖
└── Dockerfile             # 容器化部署
```

## 核心实现亮点

### 1. 混合召回检索（Hybrid Retrieval）
```python
# 向量检索 + BM25 关键词检索 + RRF 融合排序
vector_results = vector_search(query_embedding)      # 语义匹配
bm25_results = bm25_search(query)                     # 关键词匹配
final_results = reciprocal_rank_fusion(vector_results, bm25_results)
```

### 2. 双模式数据库架构
- **开发模式**：SQLite + ChromaDB，零配置启动
- **生产模式**：PostgreSQL + pgvector，高性能并发
- 自动检测环境变量切换，无需修改代码

### 3. 多模态消息处理
- 自动检测消息类型（文本/图片/文档）
- 动态选择模型：qwen-plus（文本）/ qwen-vl-plus（图文）
- 支持图片 URL 和 base64 两种格式

### 4. 流式响应优化
- 512 字节小块传输，平滑打字机效果
- 后端 `sys.stdout.flush()` 确保实时推送
- 前端增量 DOM 更新，避免闪烁

## 开发计划

- [x] 基础对话功能
- [x] 语音输入与识别
- [x] 多模态文件上传（图片/PDF/Word）
- [x] 知识库与 RAG 检索
- [x] 混合召回（向量 + BM25）
- [x] 访客限制与会话管理
- [x] 三步新手引导
- [ ] 重排序优化（Cross-Encoder）
- [ ] 历史会话向量检索
- [ ] 多语言支持
- [ ] 导出更多格式（PDF、Word）

## License

MIT License

## 致谢

- [阿里云 DashScope](https://dashscope.aliyun.com/) 提供大模型 API
- [通义千问](https://tongyi.aliyun.com/) 提供强大的对话与多模态能力
- [Cloudflare R2](https://www.cloudflare.com/developer-platform/r2/) 提供对象存储
