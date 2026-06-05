# BTC Signal Pro

A production-grade Bitcoin trading signal application with real-time WebSocket data, 6 layers of technical analysis, news sentiment, and mobile push alerts.

## Architecture

```
btc-signal-pro/
├── backend/                  FastAPI + Python 3.11
│   ├── main.py               App entry point, REST + WebSocket routes
│   ├── config.py             Pydantic settings (loaded from .env)
│   ├── indicators/
│   │   ├── calculator.py     RSI, MACD, EMA, Bollinger Bands, Volume
│   │   └── binance_ws.py     Live BTCUSDT WebSocket client
│   ├── signals/
│   │   ├── engine.py         Confidence-scored signal generator
│   │   └── backtester.py     Historical performance backtesting
│   ├── news/
│   │   ├── fetcher.py        CoinDesk, Reuters, Fear&Greed, Glassnode, CoinGlass
│   │   ├── sentiment.py      VADER + crypto-domain keyword boost
│   │   └── filter.py         Jaccard-trigram fake-news cross-reference filter
│   ├── alerts/
│   │   └── manager.py        Firebase FCM + WebSocket broadcast + DB log
│   ├── database/
│   │   ├── models.py         SQLAlchemy ORM models
│   │   └── connection.py     Async PostgreSQL engine + session factory
│   └── tests/                56 unit tests (100% pass rate)
├── frontend/                 React 18 + TypeScript + Tailwind CSS
│   └── src/
│       ├── pages/Dashboard   Main trading dashboard
│       ├── components/       SignalBadge, IndicatorsPanel, FearGreedGauge, etc.
│       ├── hooks/            useWebSocket, useApi
│       └── utils/            types.ts, format.ts
├── docker-compose.yml        Full local stack (Postgres + Backend + Frontend)
├── railway.json              Railway.app deploy config
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

### Backend

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env  # fill in values
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Run Tests

```bash
cd backend
pytest
```

## Signal Logic

A signal fires when:
1. **≥ 3 technical indicators agree** on direction (bullish/bearish)
2. **Weighted confidence score ≥ 70%** (configurable via `SIGNAL_CONFIDENCE_THRESHOLD`)

| Signal Type | Indicators Agreed | Confidence |
|-------------|-------------------|------------|
| STRONG BUY  | 4+                | ≥ 85%      |
| BUY         | 3+                | ≥ 70%      |
| STRONG SELL | 4+                | ≥ 85%      |
| SELL        | 3+                | ≥ 70%      |

Take-profit and stop-loss are calculated from Bollinger Band width (volatility-adjusted).

## Environment Variables

See [`.env.example`](.env.example) for the full list with descriptions.

Required for live trading:
- `DATABASE_URL` — PostgreSQL connection string
- `BINANCE_API_KEY` / `BINANCE_API_SECRET` — Binance account

Optional features:
- Firebase credentials — enables mobile push notifications
- `GLASSNODE_API_KEY` — on-chain metrics
- `COINGLASS_API_KEY` — liquidation data

## Deploy to Railway

1. Push this repo to GitHub
2. Create a new project on [Railway.app](https://railway.app)
3. Add a PostgreSQL service
4. Set all environment variables from `.env.example`
5. Deploy — Railway picks up `railway.json` automatically
