# AI 3D 形象生成服务 — 设计文档

- **日期**: 2026-07-04
- **状态**: Approved
- **相关记忆**: [[pixel-avatar-evolution-prototype]]

## 1. 背景与目标

产品需要给用户生成 3D 潮玩风形象。此前的探索（见 `scripts/` 实验代码）验证了完整可行的管线：
文字提示词 →（Gemini 图像模型）→ 潮玩3D风角色图 →（阿里云百炼托管的 Tripo 图生3D）→ 可嵌网页的 GLB 3D 模型。

本项目把该管线固化为**一个常驻后端服务 + HTTP API**，交付给产品团队移植。产品前端调用此 API，服务端跑完整处理逻辑并托管产出，返回稳定 URL。**本服务只做后端，不涉及产品 UI。**

### 非目标 (Non-goals)
- 不做产品前端 UI（由产品团队自己接）。
- 一次调用只出**单个** 3D 形象；不在服务内做多阶段进化链（产品端可多次调用自行编排）。
- 不做用户账号、鉴权体系（可后续加 token，本期不做）。
- 不做抗重启的持久化任务队列（本期用内存 + 本地文件，够用即可，YAGNI）。

## 2. 定位与边界

- **形态**: 常驻 FastAPI 服务（Python）。选常驻而非"随调随跑"，因为图生3D 是异步长任务（90s~数分钟），需要进程持有任务状态、轮询上游、下载并托管 GLB。
- **自包含**: 独立目录 `avatar_service/`，不塞进现有 `backend/`。产品团队可整体搬迁或独立部署。依赖极少：`fastapi`, `uvicorn`, `requests`, `pillow`, `python-dotenv`。
- **安全**: 上游 API key（`GEMINI_API_KEY`, `DASHSCOPE_API_KEY`）只存在于本服务的 `.env`，永不下发到产品前端。
- **输入**: 一句文字提示词 + 风格参数（`3d` 默认 / `pixel`）+ 可选外壳。
- **产出**: 单个 3D 形象 = GLB 模型 + 预览图 + 源图，异步生成，本服务托管为长期有效 URL。

## 3. 技术栈与形态

- 常驻 FastAPI + uvicorn。
- 任务存储：进程内内存字典（job 状态）+ 本地文件系统（GLB/预览/源图）。
- 后台执行：提交后用后台线程（`BackgroundTasks` 或 `threading`）跑管线，主请求立即返回 `job_id`。
- 目录结构：
  ```
  avatar_service/
    app.py            # FastAPI 应用：3 个端点 + 静态资产挂载
    pipeline.py       # 核心管线：prompt→图→3D→托管（框架无关，可单测）
    gemini_client.py  # Gemini 图像生成封装
    tripo_client.py   # 百炼 Tripo 图生3D 封装（提交+轮询+下载，含重试）
    store.py          # job 状态存储 + 资产文件存储
    config.py         # 从 .env 读配置
    assets/           # 托管的 GLB/预览/源图（gitignored）
    requirements.txt
    .env.example
    README.md         # 安装/启动/部署
    API.md            # 接口使用说明
    Dockerfile
  ```

## 4. 接口设计

### 4.1 POST /avatars — 提交生成
请求体：
```json
{ "prompt": "看银行账单的财务团子", "style": "3d", "shell": "creature" }
```
- `prompt` (必填, string): 形象描述。
- `style` (可选, 默认 `"3d"`): `"3d"`（潮玩/泡泡玛特风）| `"pixel"`（粗像素风）。
- `shell` (可选, string): 基础形象外壳，如 `creature`/`humanoid`/`ai_spirit`；缺省则纯用 prompt。

响应 `200`：
```json
{ "job_id": "abc123", "status": "pending" }
```

### 4.2 GET /avatars/{job_id} — 轮询状态
响应：
```json
{
  "job_id": "abc123",
  "status": "pending | running | succeeded | failed",
  "progress": "generating_image | converting_3d | downloading | done",
  "result": {
    "glb_url": "/assets/abc123.glb",
    "preview_url": "/assets/abc123.webp",
    "source_image_url": "/assets/abc123.png"
  },
  "error": null
}
```
- `result` 仅在 `succeeded` 时非空。
- `error` 仅在 `failed` 时为明确文案。
- 字段随 style 变化：`style:"3d"` → `glb_url` + `preview_url` + `source_image_url`；`style:"pixel"` → `glb_url` 为 `null`，改提供 `image_url`（静态 PNG）。产品主路径是 `3d`，`pixel` 为次要扩展路径。

### 4.3 GET /assets/{file} — 静态资产
返回托管的 GLB / 预览图 / 源图，长期有效（由本服务的静态目录提供）。

### 4.4 内部管线（一次 job）
1. `generating_image`: prompt(+shell+style 系统提示词) → Gemini 出图（`pixel` 风格额外做粗像素后处理；`3d` 风格保持平滑）。
2. `converting_3d`: 图（base64）→ 百炼 Tripo 提交任务 → 轮询至 SUCCEEDED（含 SSL 抖动自动重试 3~5 次）。
3. `downloading`: 下载 Tripo 返回的 GLB（原始 URL 2h 过期）→ 存本地 `assets/` → 生成稳定 URL。
4. `done`: 写入 `result`，状态置 `succeeded`。

`pixel` 风格无 3D 模型（图生3D 仅对 3D 风格有意义）——本期 `pixel` 返回图/动画资产而非 GLB；**若产品只需 3D，风格默认 `3d` 即可**。（注：接口保留 style 参数以备扩展；MVP 主路径是 `3d`→GLB。）

## 5. 错误处理

- 每步失败 → job `status:"failed"` + 明确 `error` 文案，HTTP 层不抛未捕获异常。
- 典型错误：上游 key 失效 / 模型未开通 / 内容被模型拒绝 / 网络抖动重试耗尽 / 输入校验失败（空 prompt）。
- 上游 SSL/握手抖动（已知 DashScope 路径 ~1/3 概率）：`tripo_client` 内置 3~5 次重试 + 退避。
- 提交端点做输入校验：空 prompt → `400`。

## 6. 配置

- 全部 key/参数从 `.env` 读（`python-dotenv`）。
- `.env.example` 提供模板（不含真实 key）：
  ```
  GEMINI_API_KEY=
  DASHSCOPE_API_KEY=
  GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
  TRIPO_MODEL=Tripo/Tripo-P1.0
  ASSET_BASE_URL=            # 可选：对外可访问的资产基址，缺省用相对 /assets
  PORT=8800
  ```

## 7. 交付物

1. `avatar_service/` 全部服务代码。
2. `README.md` — 安装、启动（本地 uvicorn）、部署（Docker）说明。
3. `API.md` — 接口使用说明：每个端点、参数、字段、示例 curl、前端轮询示例代码（JS fetch）。
4. `.env.example`、`Dockerfile`、`requirements.txt`。

## 8. 测试策略

- `pipeline.py` / 各 client 做成框架无关、可单测：用假的上游响应验证状态流转、错误归类、重试逻辑（mock 上游 HTTP）。
- **真环境验证（必须）**：mock 绿不算数。用真 key 跑一次真 `POST /avatars` → 轮询 → 拿到可访问的 GLB URL → 浏览器 `<model-viewer>` 能加载。这一步验证架构假设（base64 输入、轮询语义、GLB 托管 URL、模型已开通）。

## 9. 风险

- 上游 DashScope 偶发 SSL 抖动 → 已用重试缓解，但重试会重复计费（失败 task 通常不计费，成功后下载失败的重试可能重复出模型）。文档需提示。
- Tripo 图生3D 对某些形象（矮胖 Q 版）绑骨/建模可能变形——本期只出静态 GLB（无绑骨），风险较低；绑骨是未来工作。
- 成本：每形象 ≈ 1 次 Gemini 出图（~$0.039）+ 1 次 Tripo（~¥0.5-1）。文档需给出量级。
- 本期内存存 job 状态：进程重启丢失进行中任务；多实例不共享。文档需注明，生产可换 Redis。

## 10. 未来工作（本期不做）

- 自动绑骨（Meshy API / 开源 Make-It-Animatable）→ 可动 3D。
- 多阶段进化链端点。
- 鉴权 token / 限流。
- 持久化任务队列（Redis）+ 对象存储（OSS）托管资产。
