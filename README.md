# 视频转 MP3 助手 · 手机端（Web App / PWA）

电脑版「视频转 MP3 助手」的手机端同款。**功能与 Windows 版一致**：

- 粘贴链接转 MP3 / FLAC（B站 / YouTube / 抖音 / 快手 等公开视频，仅处理你有权下载的内容）
- 三档音质：普通 128k MP3 / 高频 320k MP3 / 无损 FLAC
- 每任务单独设置：裁剪长度（开始/结束/最大时长）、自定义标题
- 任务队列：进度、停止（取消）、重试、删除、并发数控制
- 写入 ID3v2.3 标签 + 封面（MP3 兼容老设备）
- SQLite 历史记录（搜索 / 删除 / 清空 / 重新下载）
- 设置：默认音质、并发数、命名模板、嵌入封面
- PWA：手机浏览器「添加到主屏幕」即当 App 使用，离线可打开界面

## 目录结构

```
E:\MP3\
├── backend\          # Flask 后端（复用核心下载/转码/标签逻辑）
│   ├── app.py        # API 服务入口
│   ├── core\         # 下载、转码、写标签、并发安全文件名
│   └── requirements.txt
├── frontend\         # 移动端前端（PWA，零构建依赖）
│   ├── index.html    # 单页应用
│   ├── css\app.css   # 蔚蓝档案清新风
│   ├── js\app.js     # 任务/历史/设置逻辑
│   ├── manifest.json # PWA 清单（图标/主题色/全屏）
│   ├── sw.js         # Service Worker 离线缓存
│   └── icons\        # App 图标（普拉娜头像）
├── data\             # 运行时数据（tmp/输出/历史库/配置）
└── tests\e2e_backend.py
```

## 本地运行

```bash
cd E:\MP3
pip install -r backend\requirements.txt
python backend\app.py
```

- 本机访问 http://127.0.0.1:8000
- 手机访问 http://<电脑IP>:8000 （同一 WiFi）

## 网页版（GitHub Pages + 免费后端，无需自己买服务器）

别人点开网页就能用全部功能，零安装。前端挂在 GitHub Pages（静态界面），后端部署在免费托管（Render 免费层，从本仓库一键拉起）。

### 1. 免费托管后端（Render，约 5 分钟，无需付费）

1. 打开 https://render.com 注册账号（Free 计划不需要绑卡）；
2. Dashboard → **New → Web Service** → 连接你的 GitHub → 选择本仓库 `VideoToMp3-Mobile`；
3. Render 自动识别 `render.yaml`，直接点 **Create Web Service**；
4. 等待部署完成，得到地址如 `https://video-to-mp3.onrender.com`。

> 免费实例闲置时休眠，首次访问需等 30-60 秒冷启动（属正常现象，之后常驻）。

### 2. 前端 GitHub Pages（可选）

本仓库 `gh-pages` 分支已托管 `frontend/` 界面：
`https://<你的GitHub用户名>.github.io/VideoToMp3-Mobile/`

### 3. 把界面指向后端

打开前端页面 → 底部「设置」→「服务地址」填 `https://video-to-mp3.onrender.com` → 保存（页面自动刷新即生效）。

> 部署后数据目录（`data/`）位于服务器实例磁盘，历史记录按实例持久化（免费实例休眠重启可能清空磁盘，属免费层限制；下载的 MP3 请及时下载保存到手机）。

## 公网部署（云服务器方式）

### 方式 A：云服务器（推荐）

1. 服务器安装 Python 3.11+：
   ```bash
   pip install -r backend/requirements.txt
   ```
2. 上传项目到服务器（如 `/opt/vmp3`）
3. 用 gunicorn + Nginx 反代（示例）：

   `/etc/systemd/system/vmp3.service`:
   ```ini
   [Unit]
   Description=Video to MP3 API
   After=network.target

   [Service]
   User=www-data
   WorkingDirectory=/opt/vmp3
   ExecStart=/usr/bin/gunicorn -w 2 -b 127.0.0.1:8000 "backend.app:APP"
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

   Nginx:
   ```nginx
   server {
       listen 443 ssl;
       server_name 你的域名;
       # ... ssl 证书配置 ...
       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_read_timeout 300;
       }
   }
   ```

4. `systemctl enable --now vmp3`

> 手机 Chrome / Edge 打开你的域名 → 右上角菜单 →「添加到主屏幕」，即变 App。

### 方式 B：内网穿透（零服务器）

- 使用 ngrok / Cloudflare Tunnel / cpolar 等将本地 8000 端口映射到公网域名（个人使用注意流量费用与安全）。

## 合规说明

- 仅处理用户主动粘贴、且用户有权下载/保存的视频链接；
- 不实现绕过 DRM、付费墙、登录限制、会员限制的功能；
- 平台明确禁止下载时，会给出中文提示并停止（错误分类：无效链接 / 网络失败 / 平台限制 / 需登录 / 未找到 / 未知）。

## API 一览

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/health` | GET | 健康检查 |
| `/api/parse` | POST | 解析单链接元数据 |
| `/api/convert` | POST | 批量添加转换任务 |
| `/api/status/<jid>` | GET | 查询任务状态/进度 |
| `/api/cancel/<jid>` | POST | 取消任务 |
| `/api/download/<jid>` | GET | 下载成品文件 |
| `/api/history` | GET | 历史记录（?q=搜索） |
| `/api/history/<id>` | DELETE | 删除单条历史 |
| `/api/history/clear` | POST | 清空历史 |
| `/api/settings` | GET/POST | 读写设置 |

## 验证记录

- 真实 B站链接端到端：解析（标题/时长/作者）→ 下载 → 转码（裁剪 60s 精确）→ 写标签（标题/作者/封面 APIC）→ 历史入库 → 下载接口，全部通过；
- 稳定性专项回归：任务去重、转码中取消、下载中取消、并发并行（2+ 任务同时跑）、取消后零临时文件残留，全部通过；
- 浏览器交互：粘贴链接 → 添加任务 → 轮询 → 完成 → 下载/删除按钮渲染正常，无控制台错误；
- 下载接口：返回真实 MP3（ID3 头校验），中文文件名 UTF-8 编码，手机浏览器直接保存到「下载」目录。
