# 配置与链接统一管理

## 后端

后端配置只从进程环境变量或项目根目录 `.env` 读取，集中定义在 `app_config.py`。`DATABASE_URL` 和 `AUTH_SECRET` 没有代码默认值，缺失时直接停止启动。

生产环境使用 `.env.prod.example` 作为字段模板，真实值由云平台 Secret、Docker `--env-file` 或密钥挂载提供，不提交 Git。

配置分组：

- 应用：`APP_ENV`、`AUTH_SECRET`、`ACCESS_TOKEN_EXPIRE_SECONDS`
- 数据库：`DATABASE_URL`
- 跨域/管理：`CORS_ORIGINS`、`ALLOW_DEV_CORS`、`ADMIN_USER_IDS`、`ADMIN_ALLOWED_IPS`
- 加密：`PERSONAL_DATA_ENCRYPTION_KEY`、`RECIPE_ENCRYPT_KEY`、`ENCRYPTION_KEY_FILE`
- 存储：`STORAGE_BACKEND`、`LOCAL_UPLOAD_DIR`、全部 `S3_*`
- 日志：`LOG_LEVEL`、`LOG_TO_FILE`、`LOG_DIR`
- OCR：`BAIDU_OCR_API_KEY`、`BAIDU_OCR_SECRET_KEY`、`BAIDU_OCR_TOKEN_URL`、`BAIDU_OCR_API_URL`

## 前端

前端所有环境相关 URL 集中在 `.env` / `.env.production`，读取和拼接逻辑集中在 `src/utils/config.js`：

- `VITE_API_BASE`：API 公共前缀；同源部署留空
- `VITE_UPLOAD_URL`：上传地址
- `VITE_OCR_URL`：OCR 地址
- `VITE_IMG_BASE`：图片公共域名；同源部署留空
- `VITE_DEV_API_TARGET`：仅开发服务器代理目标
- `VITE_DEV_HMR_HOST`：仅跨设备调试需要；本机开发留空

页面路径常量和带参数链接从 `src/utils/routes.js` 引用。新增页面导航时先在这里登记，禁止在业务代码新增重复的根路径字符串。

项目不提供微信登录，也不保留微信 AppID、Secret、openid 或微信开发者工具项目配置。

## 约束

- 源码中不允许出现局域网 IP、生产域名、数据库账号密码或静态 Token。
- 相对 API/图片地址统一通过配置工具拼接，避免双斜杠和重复 `/api`。
- Vite 代理前缀只在 `vite.config.js` 的 `API_PROXY_PREFIXES` 维护一份。
- Nginx 对外路径由 `deploy/nginx.conf` 维护；新增后端一级路由时同步加入代理检查。

## 图片路径约定

- 数据库只保存与域名无关的相对路径，不保存开发机 IP、端口或前端拼接后的完整 URL。
- 配方图片固定使用 `/uploads/recipes/<文件名>`，作品图片固定使用 `/uploads/works/<文件名>`。
- 前端上传时分别调用 `uploadRecipeImage`、`uploadWorkImage`；保存前统一调用 `normalizeImagePath`，展示时统一调用 `resolveImage`。
- `cover` / `image` 保存主图路径，`images` 保存合法 JSON 数组；主图同时包含在数组中。
- 已有本地数据先用 `python scripts/organize_images.py --apply` 整理配方/作品目录，再用 `python scripts/finalize_image_cleanup.py --apply` 导入可用外链、清除失效地址并清理根目录旧文件。
