# 财务对账系统 (Financial Reconciliation System)

电商测评费用财务对账系统，替代 Excel 工作流。核心业务：客户 ↔ 我司 ↔ FO机构 的应收/应付账款管理。

## 技术栈

- 后端: Python Flask + SQLite
- 前端: Vue 3 + Element Plus (CDN)
- 部署: Render (auto-deploy from GitHub main)

## 本地开发

```bash
pip install -r requirements.txt
python app.py
# 访问 http://localhost:5000
```

## 部署 (Render)

1. 推送代码到 GitHub main 分支
2. Render 自动从 main 分支部署
3. 配置文件: `render.yaml`

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| PORT | 服务端口 | 5000 |
| DB_PATH | SQLite 数据库路径 | ./reconciliation.db |
| UPLOAD_DIR | 上传文件目录 | ./static/uploads |

## 功能

- 财务看板（应收/应付/逾期/状态分布）
- 对账流水管理（新增/编辑/删除/筛选）
- 客户收款（AR管理）
- 货值付款 + 佣金付款（AP管理，分开付款因为货币不同）
- 凭证截图上传（支持 Ctrl+V 粘贴）
- 汇率管理
- 审计日志
- 自定义列显示/隐藏
