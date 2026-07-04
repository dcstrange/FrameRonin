# Avatar 3D Service — API 文档

服务默认监听 `http://localhost:8800`。异步任务模型：先 `POST /avatars` 拿到 `job_id`，再轮询 `GET /avatars/{job_id}`，成功后用产物 URL（`GET /assets/{file}`）渲染。

## 参数取值表

| 字段 | 取值 | 默认 | 说明 |
|---|---|---|---|
| `style` | `3d` \| `pixel` | `3d` | `3d` 走 Gemini→Tripo 出 GLB；`pixel` 只出像素 PNG |
| `shell` | `creature` \| `humanoid` \| `ai_spirit` \| `null` | `null` | 可选的形态提示，`null`/省略表示不限定 |

---

## 1. `POST /avatars` — 提交任务

**请求体**：

```json
{
  "prompt": "a wise old turtle sage",
  "style": "3d",
  "shell": "creature"
}
```

- `prompt`（**必填**，string）：空字符串或纯空白 → **HTTP 400**。
- `style`（可选）：见上表，默认 `"3d"`。
- `shell`（可选）：见上表，默认 `null`。

**响应**（立即返回，任务在后台线程运行）：

```json
{ "job_id": "e2b1c9a4-...", "status": "pending" }
```

---

## 2. `GET /avatars/{job_id}` — 轮询状态

任务不存在 → **HTTP 404**。

**响应结构**：

```json
{
  "job_id": "e2b1c9a4-...",
  "status": "pending | running | succeeded | failed",
  "progress": "generating_image | converting_3d | downloading | done | null",
  "result": { "...": "..." } ,
  "error": "错误信息字符串 | null"
}
```

- `status` 流转：`pending` → `running` → `succeeded` / `failed`。
- `progress`（3D）：`generating_image` → `converting_3d` → `downloading` → `done`。
- `progress`（pixel）：`generating_image` → `done`。
- 失败时 `status:"failed"`，`error` 为原因字符串，`result` 为 `null`。

### result 字段差异（按 style）

**`style:"3d"` 成功时**：

```json
{
  "glb_url": "/assets/e2b1c9a4-....glb",
  "preview_url": "/assets/e2b1c9a4-....png",
  "source_image_url": "/assets/e2b1c9a4-....png"
}
```

**`style:"pixel"` 成功时**：

```json
{
  "glb_url": null,
  "image_url": "/assets/e2b1c9a4-....png"
}
```

> 注意：3D 结果里 `preview_url` 与 `source_image_url` 指向同一张源图（源图兼作预览图）；pixel 结果**没有** `glb_url`（为 `null`），只有 `image_url`。

---

## 3. `GET /assets/{file}` — 获取产物

静态托管 GLB / 预览图 / 源图。`result` 里的 URL 直接指向此路由。

- 若未设 `ASSET_BASE_URL`，返回的是**相对路径** `/assets/...`，需自行拼接服务 origin。
- 若设了 `ASSET_BASE_URL`，返回的是**绝对地址** `{ASSET_BASE_URL}/assets/...`。

---

## curl 示例：提交 → 轮询

```bash
# 1) 提交，拿 job_id
JOB=$(curl -s -X POST http://localhost:8800/avatars \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"a wise old turtle sage","style":"3d","shell":"creature"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')

# 2) 轮询状态
curl -s http://localhost:8800/avatars/$JOB
# => {"job_id":"...","status":"running","progress":"converting_3d","result":null,"error":null}

# 成功后
# => {"job_id":"...","status":"succeeded","progress":"done",
#     "result":{"glb_url":"/assets/....glb","preview_url":"/assets/....png","source_image_url":"/assets/....png"},
#     "error":null}
```

---

## JavaScript `fetch` 轮询示例

提交 → 每 4 秒轮询一次 → 成功后把 `glb_url` 塞进 `<model-viewer>`：

```js
const ORIGIN = "http://localhost:8800"; // 若设了 ASSET_BASE_URL 且 URL 已是绝对地址，则可省略拼接

async function createAvatar(prompt) {
  // 1) 提交
  const res = await fetch(`${ORIGIN}/avatars`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, style: "3d", shell: null }),
  });
  const { job_id } = await res.json();

  // 2) 每 4s 轮询直到 succeeded / failed
  const job = await new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      const r = await fetch(`${ORIGIN}/avatars/${job_id}`);
      const j = await r.json();
      if (j.status === "succeeded") { clearInterval(timer); resolve(j); }
      else if (j.status === "failed") { clearInterval(timer); reject(new Error(j.error)); }
      // 否则继续轮询（pending / running）
    }, 4000);
  });

  // 3) 成功：把 glb_url 塞进 <model-viewer>
  const viewer = document.querySelector("model-viewer");
  // 若返回是相对路径，拼上 origin；若已是绝对地址（ASSET_BASE_URL），直接用
  const glb = job.result.glb_url.startsWith("http")
    ? job.result.glb_url
    : `${ORIGIN}${job.result.glb_url}`;
  viewer.src = glb;
}
```

---

## `<model-viewer>` 内嵌 HTML 片段

引入 Google 的 `<model-viewer>` web component 即可在网页上展示 GLB：

```html
<script type="module"
        src="https://unpkg.com/@google/model-viewer"></script>

<model-viewer
  src="{glb_url}"
  camera-controls
  auto-rotate>
</model-viewer>
```

把 `{glb_url}` 替换为 `result.glb_url`（必要时拼上服务 origin）。`camera-controls` 允许鼠标拖拽旋转，`auto-rotate` 自动旋转。

---

## 跨域部署注意

- 如果**服务**和**前端产品**在不同 origin，请设置 `ASSET_BASE_URL`，让返回的 `glb_url` / `image_url` 等成为**绝对地址**，否则前端拿到的相对路径 `/assets/...` 会指向错误的 origin。
- 跨 origin 加载 GLB / 图片时可能需要在服务端**开启 CORS**（允许目标前端 origin）。当前服务未内置 CORS 配置，属本文档范围之外，但**部署前请留意**。
