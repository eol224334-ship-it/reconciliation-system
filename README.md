# 测评对账系统 (Review Reconciliation System)

电商测评费用对账系统，替代 Excel 工作流。核心业务：客户 ↔ 我司 ↔ FO机构 的应收/应付账款管理。

## 技术栈

- 后端: Python Flask + SQLite
- 前端: Vue 3 + Element Plus (CDN)
- 部署: Render (auto-deploy from GitHub main)

## 功能

- 财务看板（应收/应付/逾期/状态分布/按币种汇总）
- 对账流水管理（新增/编辑/删除/筛选）
- 客户收款（AR管理）
- 货值付款 + 佣金付款（AP管理，分开付款因为货币不同）
- 支持 20 种货币（IDR/THB/VND/MYR/PHP/SGD/BRL/MXN/COP/CLP/USD/CNY/EUR/JPY/KRW/GBP/AUD/TRY/PLN/INR）
- 飞书机器人通知（Webhook + HMAC-SHA256 签名验证）
- 凭证截图上传（支持 Ctrl+V 粘贴）
- 汇率管理 + 自动获取最新汇率
- 审计日志
- 自定义列显示/隐藏
- 先收款后付款业务校验

## 本地开发

```bash
pip install -r requirements.txt
python app.py
# 访问 http://localhost:5000
```

## 部署 (Render)

### 一键部署

点击以下链接，Render 会自动读取 `render.yaml` 配置：

👉 **[Deploy to Render](https://render.com/deploy?repo=https://github.com/eol224334-ship-it/reconciliation-system)**

### 部署步骤

1. 点击上方部署链接
2. 登录 Render（可用 GitHub 账号登录）
3. 授权 Render 访问 GitHub 仓库
4. 确认配置（render.yaml 已预填）
5. 点击 **Apply** 开始部署
6. 等待构建完成（约 2-3 分钟）
7. 部署成功后获得 `https://xxx.onrender.com` 访问地址

### 后续更新

修改代码 → `git push origin main` → Render 自动重新部署

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| PORT | 服务端口（Render 自动设置） | 5000 |
| DB_PATH | SQLite 数据库路径 | ./reconciliation.db |
| UPLOAD_DIR | 上传文件目录 | ./static/uploads |

### 数据持久化说明

- **Free 计划**: 数据存储在容器临时文件系统中，每次重新部署数据会重置
- **Starter 计划** ($7/月): 可添加持久化磁盘（Disk），数据跨部署保留
- 升级后在 Render Dashboard → Service → Disks 中添加磁盘，挂载到 `/data`，并设置环境变量 `DB_PATH=/data/reconciliation.db`
