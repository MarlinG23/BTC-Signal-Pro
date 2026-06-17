# BTC Signal Pro

A production-grade Bitcoin trading signal application with real-time WebSocket data, 6 layers of technical analysis, news sentiment, and mobile push alerts.

## Architecture

```
btc-signal-pro/
├── backend/                  FastAPI + Python 3.11
│   ├── main.py               App entry point, REST + WebSocket routes
│   ├── config.py             Pydantic settings (loaded from .env)
│   ├── indicators/
│   │   ├── calculator.py     RSI, MACD, EMA, Bollinger Bands, Volume, ATR
│   │   └── binance_ws.py     Live BTCUSDT WebSocket client (Binance.US)
│   ├── signals/
│   │   ├── engine.py         Confidence-scored signal generator
│   │   └── backtester.py     Historical performance backtesting
│   ├── news/
│   │   ├── fetcher.py        CoinDesk, CoinTelegraph, Bitcoin Magazine, Fear&Greed
│   │   ├── sentiment.py      VADER + crypto-domain keyword boost
│   │   └── filter.py         Cross-reference quality badge (non-blocking)
│   ├── alerts/
│   │   └── manager.py        Firebase FCM + WebSocket broadcast + DB log
│   ├── database/
│   │   ├── models.py         SQLAlchemy ORM models
│   │   └── connection.py     Async PostgreSQL engine + session factory
│   └── tests/                Unit tests
├── frontend/                 React 18 + TypeScript + Tailwind CSS
│   └── src/
│       ├── pages/Dashboard   Main trading dashboard
│       ├── components/       SignalBadge, TrendPanel, StatusBar, etc.
│       ├── hooks/            useWebSocket, useApi
│       └── utils/            types.ts, format.ts
├── docker-compose.yml        Full local stack (Postgres + Backend + Frontend)
├── railway.toml              Railway backend deploy config
├── frontend/railway.toml     Railway frontend deploy config
└── .env.example              All environment variables documented
```

## Quickstart (Docker)

```bash
cp .env.example .env
# Fill in your API keys in .env
docker-compose up --build
```

Frontend → http://localhost:3000  
Backend API → http://localhost:8000  
API Docs → http://localhost:8000/docs

## Local Development

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 16 (or use Docker Compose for the database only)

### Backend

```bash
cp .env.example .env
# Set DATABASE_URL to your local Postgres instance
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

On Windows without PostgreSQL, the backend starts in no-persistence mode (signals and news won't be stored). Use Docker Compose or Railway for full functionality.

Set `BINANCE_USE_US_ENDPOINT=true` if running on US infrastructure (default).

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` and `/ws` to `http://localhost:8000`.

### Run Tests

```bash
cd backend
pytest
```

## Signal Logic

A signal fires when:
1. **≥ 3 technical indicators agree** on direction (bullish/bearish)
2. **Weighted confidence score ≥ 70%** (`SIGNAL_CONFIDENCE_THRESHOLD`)
3. **4H trend confirms** the 1M entry direction
4. **Fear & Greed filter** — BUY when F&G < 40, SELL when F&G > 60

| Signal Type | Indicators Agreed | Confidence |
|-------------|-------------------|------------|
| STRONG BUY  | 4+                | ≥ 85%      |
| BUY         | 3+                | ≥ 70%      |
| STRONG SELL | 4+                | ≥ 85%      |
| SELL        | 3+                | ≥ 70%      |

Take-profit and stop-loss use **ATR(14)**:
- TP distance = max(ATR × 2, 0.5% of entry)
- SL distance = max(ATR × 1, 0.3% of entry)

## API Documentation

Interactive docs: `http://localhost:8000/docs` (Swagger UI)

### Key REST Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Liveness probe (503 until startup complete) |
| `GET /api/status` | Full operational snapshot (candles, WS, news, DB) |
| `GET /api/indicators` | Latest 1M indicator snapshot |
| `GET /api/indicators/4h` | Latest 4H trend indicator snapshot |
| `GET /api/fear-greed` | Current Fear & Greed index |
| `GET /api/news?limit=30` | Recent news articles with sentiment |
| `GET /api/signals/latest?limit=20` | Recent trading signals |
| `GET /api/signals/stats` | Win rate and outcome statistics |
| `GET /api/alerts/history?limit=50` | Alert log |
| `GET /api/backtest?days=30` | Run backtest over stored candles |
| `WS /ws` | Live price ticks, indicators, signals, news |

### WebSocket Message Types

- `price_tick` — live BTC price update
- `indicators` — 1M indicator snapshot on candle close
- `signal` — new trading signal fired
- `news` — breaking news alert
- `fear_greed` — Fear & Greed index update
- `alert` — price level or system alert

## Environment Variables

See [`.env.example`](.env.example) for the full list with descriptions.

Required for production:
- `DATABASE_URL` — PostgreSQL connection string (asyncpg driver)

Recommended on Railway US:
- `BINANCE_USE_US_ENDPOINT=true` — use Binance.US (geo-block workaround)

Optional features:
- Firebase credentials — mobile push notifications
- `GLASSNODE_API_KEY` — on-chain metrics
- `COINGLASS_API_KEY` — liquidation data

## Deploy to Railway

1. Push this repo to GitHub
2. Create a project on [Railway.app](https://railway.app)
3. Add a **PostgreSQL** service
4. Deploy **BTC-Signal-Pro** (backend) — uses root `railway.toml`
5. Deploy **frontend** — uses `frontend/railway.toml`
6. Set frontend `BACKEND_URL` to the backend public URL
7. Set backend `CORS_ORIGINS` to the frontend public URL
8. Set all other variables from `.env.example`

GitHub Actions (`.github/workflows/deploy.yml`) runs `railway up --service BTC-Signal-Pro` on push to `main`. Requires `RAILWAY_TOKEN` secret.

Production URLs (example):
- Frontend: https://frontend-production-9f903.up.railway.app
- Backend: https://btc-signal-pro-production-9401.up.railway.app
