# pyharmonics-gpt

This is a docker project that will integrate pyharmonics with any OpenAI models.  You will need an open ai API key for your model.
This project will work with any model that is implemented with the openai API spec.  That includes deepseek, GPT, daVinci e.t.c
Please see the model pricing structure to determine which model works best for you.


When you are up and running you can ask your model questions like.

```
Are there tradable patterns for BTCUSDT on the 15min time frame?
```

The model will then leverage pyharmonics to respond to your query.

NOTE: You must ask a question that can be converted into arguments for pyharmonics chart analysis.  If you attempt to build this for your own application then you need to consider how you want to limit the range of queries and map those your own API.

### What assets are supported.

Stock symbols in yahoo finance e.g MSFT, AAPL, TSLA etc.
Crypto pairs on binance e.g. BTCUSDT, ETHUSDT, SOLUSDT etc.

Time frames supported are 1m, 15m, 1h, 4h, 1d, 1w.

# Installation

## Clone Repo

Requires docker and python to be installed on your machine.
Requires an OpenAI API key.
```
> git clone git@github.com:niall-oc/pyharmonics-gpt.git
> cd pyharmonics-gpt
```

## OpenAI API key

You can explicitly set the key in code, but the risk of commiting code with keys in it is unacceptable.  Instead use your environment to hold the keys.

### Use env file ( Easiest method on desktop )
Create a file in the pyharmonics-gpt called ```.env```. Add the following line so python-dotenv can load your key.

```
OPENAI_API_KEY=YOUR_KEY_GOES_HERE
OPENAI_API_MODEL=gpt-3.5-turbo
OPENAI_API_BASE_URL=https://api.openai.com/v1
```

### Use environment variable ( Easiest method on server/cloud deployment )
On a bash shell do the following.
```
> export OPENAI_API_KEY=YOUR_KEY_GOES_HERE
> export OPENAI_API_MODEL=gpt-3.5-turbo
> export OPENAI_API_BASE_URL=https://api.openai.com/v1
```

### Edit/use the docker file ( Works but your key would be part of the repo if you accidentally commit! )
Add the following line to the Dockerfile

```
# Set your open API key
ENV OPENAI_API_KEY=YOUR_KEY_GOES_HERE
ENV OPENAI_API_MODEL=gpt-3.5-turbo
ENV OPENAI_API_BASE_URL=https://api.openai.com/v1
```

## Run the docker image
```
pyharmonics-gpt > sudo docker-compose up --build
```

## Visit the web page and query GPT with pharmonics api integrated.
Then visit http://localhost:5000 to interact with the GPT prompt enabled with pyharmonics.

See the video tutorial for more. https://www.youtube.com/watch?v=GZ-O5SlJjVc

![Desktop UI](pyharmonics.png)

---

## 新版 SaaS 前端（Beta）

项目已新增基于 Next.js 14 + TypeScript + Tailwind CSS 的 SaaS 前端，参考 `docs/frontend-design-2026-07-14.md` 实现。

### 本地开发启动

1. 启动 TradingView 数据桥（主要实时数据源）：

```bash
cd tradingview-bridge
npm install
npm start
# 默认端口 5002；健康检查 http://127.0.0.1:5002/health
```

2. 启动后端（macOS 的 Control Center 会占用 5000，因此本地使用 5001 并开启开发鉴权 bypass）：

```bash
source .venv/bin/activate
DISABLE_AUTH=1 PORT=5001 gunicorn --config gunicorn.conf.py app.main:app
```

3. 启动前端（另开终端）：

```bash
cd frontend
cp .env.example .env.local
# 配置 NEXT_PUBLIC_SUPABASE_URL 与 NEXT_PUBLIC_SUPABASE_ANON_KEY
npm install
BACKEND_API_BASE=http://127.0.0.1:5001 npm run dev
```

本地开发时，Next.js 会将 `/api/*` 请求代理到后端的 Flask 服务（默认 `http://127.0.0.1:5001`，可通过 `BACKEND_API_BASE` 覆盖）。

> `DISABLE_AUTH=1` 仅用于本地开发，生产环境必须关闭（`DISABLE_AUTH=0`）。
>
> TradingView 桥默认启用。若桥接服务不可用，后端会自动降级到 Binance/Yahoo。可通过 `USE_TRADINGVIEW=false` 关闭 TradingView 优先策略。

主要页面：
- `/login` — 邮箱魔法链接登录
- `/dashboard` — 分析工作台
- `/history` — 历史记录
- `/settings` — 账户与主题
- `/admin` — 管理员面板
