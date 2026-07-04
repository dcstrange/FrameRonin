# Avatar 3D Service

一个常驻的 FastAPI 服务，把一段文字 prompt 转成 **3D 头像（GLB）** 或 **像素头像（PNG）**。

接口细节见 [API.md](./API.md)。

## 服务简介

- **异步任务模型**：`POST /avatars` 立即返回 `{job_id, status:"pending"}`，客户端用 `GET /avatars/{job_id}` 轮询直到 `succeeded`/`failed`，产物通过 `GET /assets/{file}` 提供。
- **3D 流水线**：prompt → Gemini 生成图片 → base64 → 阿里云百炼（DashScope）Tripo image-to-3D（提交 + 轮询约 90s，带 SSL 抖动重试）→ 下载 GLB → 本地托管 → 返回稳定 URL。
- **像素流水线**：prompt → Gemini 生成图片 → 粗像素化后处理 → 本地托管 PNG。
- 产物文件托管在 `ASSET_DIR` 下，通过 `/assets/...` 静态路由对外提供。

## 安装

从**仓库根目录**执行（`avatar_service` 需作为包被导入）：

```bash
python3 -m venv avatar_service/.venv
avatar_service/.venv/bin/pip install -r avatar_service/requirements.txt
```

## 配置

复制示例环境文件并填写：

```bash
cp avatar_service/.env.example avatar_service/.env
```

至少填写这两个：

- `GEMINI_API_KEY` — Google AI Studio 的 API key（图片生成）
- `DASHSCOPE_API_KEY` — 阿里云百炼（DashScope）的 API key（3D 转换）

> **必须在百炼控制台开通 Tripo-3D 模型**。在 [阿里云百炼](https://bailian.console.aliyun.com) 的**模型市场**里一次性激活 Tripo-3D 模型，否则任务会以 `product is not activated` 失败。这是一次性动作，但每个百炼账号都要做一次。

其余可选环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `GEMINI_IMAGE_MODEL` | `gemini-3.1-flash-image` | Gemini 图片模型 |
| `TRIPO_MODEL` | `Tripo/Tripo-P1.0` | 百炼上的 Tripo 3D 模型名 |
| `ASSET_DIR` | `assets` | 产物落盘目录 |
| `ASSET_BASE_URL` | 空 | 若设置，返回的 URL 变为绝对地址 `{ASSET_BASE_URL}/assets/...`（跨域部署时需要，详见 API.md） |
| `PORT` | `8800` | 监听端口 |

## 本地启动

从**仓库根目录**执行：

```bash
avatar_service/.venv/bin/uvicorn avatar_service.app:get_app --factory --port 8800
```

`--factory` 指向 `get_app()` 工厂函数。必须在仓库根目录运行，`avatar_service` 才能作为包正确导入。启动后服务监听 `http://localhost:8800`。

## Docker 部署

**构建上下文是仓库根目录**（Dockerfile 里 `COPY avatar_service ...` 依赖此点）：

```bash
docker build -f avatar_service/Dockerfile -t avatar-3d-service .

docker run -p 8800:8800 \
  --env-file avatar_service/.env \
  -v $(pwd)/avatar_service/assets:/app/avatar_service/assets \
  avatar-3d-service
```

挂载 `assets` 卷是为了让生成的 GLB/PNG 在容器重建后仍然保留。

## 运行测试

从仓库根目录执行：

```bash
avatar_service/.venv/bin/python -m pytest avatar_service
```

## 成本说明

数量级参考（真实数字以 [Google AI Studio](https://aistudio.google.com) 与阿里云**费用中心**控制台为准）：

- 每张 Gemini 图片 ≈ **$0.039**
- 每个 Tripo 3D 模型 ≈ **¥0.5 – 1**
- 合计每个成品 3D 头像 ≈ **$0.15 / ¥1**

像素风只产生 Gemini 图片成本，不走 Tripo，故明显更便宜。

## 已知限制

- **内存态任务存储**：job 状态在进程内存里，服务重启会丢失进行中的任务。仅支持**单实例**部署，不能水平扩展。
- **可能重复计费**：对百炼的瞬时 SSL 错误会自动重试；如果某次重试发生在一次已计费的成功之后，理论上可能造成**双重计费**。
- 产物文件持续累积占用 `ASSET_DIR` 磁盘，需自行定期清理。
