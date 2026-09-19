# Fund Agent 前端

React 19 + TypeScript + Vinext/Vite 前端，连接 `backend/` 目录中的 FastAPI 服务。

## 本地启动

先在 `backend/` 目录启动后端：

```powershell
cd backend
D:\python\env\fund_agent\Scripts\python.exe scripts\run_local.py --reload
```

再新开一个终端启动前端：

```powershell
cd frontend
$env:Path = 'D:\software\nvm\v22.23.2;' + $env:Path
npm run dev
```

打开 <http://localhost:3000>。后端 API 默认地址为
`http://localhost:8000/api/v1`，可复制 `.env.example` 为 `.env.local` 后覆盖。

## 检查

```powershell
npm run lint
node .\node_modules\typescript\bin\tsc --noEmit --incremental false
npm run build
```
