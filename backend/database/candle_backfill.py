"""
Historical 1M candle backfill from Binance REST into PostgreSQL.

Fetches closed 1-minute klines in batches of up to 1000 and upserts them
into price_candles. Safe to run repeatedly — duplicates are skipped.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import PriceCandle
from indicators.binance_ws import REST_BASE_COM, REST_BASE_US, SYMBOL_UPPER

logger = logging.getLogger(__name__)

ONE_MINUTE_MS = 60_000
BATCH_LIMIT = 1000


async def count_candles_since(session: AsyncSession, since: datetime) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(PriceCandle)
        .where(PriceCandle.open_time >= since)
    )
    return int(result.scalar_one())


async def backfill_1m_candles(
    session: AsyncSession,
    days: int = 30,
) -> dict:
    """
    Pull closed 1M klines from Binance REST until at least ``days`` calendar
    days of candles exist in the DB (counting from now backwards).

    Returns a summary dict with counts and the actual date span stored.
    """
    if days < 1 or days > 90:
        raise ValueError("days must be between 1 and 90")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    existing = await count_candles_since(session, cutoff)
    target = days * 24 * 60  # closed 1M bars in N days

    if existing >= target:
        oldest = await session.execute(
            select(func.min(PriceCandle.open_time)).where(
                PriceCandle.open_time >= cutoff
            )
        )
        oldest_ts = oldest.scalar_one()
        return {
            "status": "already_sufficient",
            "days_requested": days,
            "candles_in_window": existing,
            "target_candles": target,
            "oldest_in_window": oldest_ts.isoformat() if oldest_ts else None,
            "inserted": 0,
            "batches_fetched": 0,
        }

    endpoints = (
        [REST_BASE_US, REST_BASE_COM]
        if settings.BINANCE_USE_US_ENDPOINT
        else [REST_BASE_COM, REST_BASE_US]
    )

    start_ms = int(cutoff.timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)
    inserted = 0
    batches = 0
    cursor_ms = start_ms

    async with httpx.AsyncClient(timeout=30) as client:
        while cursor_ms < end_ms:
            batch_end_ms = min(cursor_ms + (BATCH_LIMIT - 1) * ONE_MINUTE_MS, end_ms)
            klines = None
            for base in endpoints:
                try:
                    resp = await client.get(
                        f"{base}/api/v3/klines",
                        params={
                            "symbol": SYMBOL_UPPER,
                            "interval": "1m",
                            "startTime": cursor_ms,
                            "endTime": batch_end_ms,
                            "limit": BATCH_LIMIT,
                        },
                    )
                    resp.raise_for_status()
                    klines = resp.json()
                    break
                except Exception as exc:
                    logger.warning("Backfill batch failed from %s: %s", base, exc)

            if not klines:
                logger.error("Backfill: no klines returned at cursor %d", cursor_ms)
                break

            batches += 1
            rows = []
            for k in klines:
                # Skip the still-open last candle when we're at the live edge
                close_time_ms = int(k[6])
                if close_time_ms >= end_ms:
                    continue
                open_time = datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc)
                close_time = datetime.fromtimestamp(close_time_ms / 1000, tz=timezone.utc)
                rows.append(
                    {
                        "open_time": open_time,
                        "open_price": float(k[1]),
                        "high_price": float(k[2]),
                        "low_price": float(k[3]),
                        "close_price": float(k[4]),
                        "volume": float(k[7]),  # USDT quote volume
                        "close_time": close_time,
                        "quote_asset_volume": float(k[7]),
                        "number_of_trades": int(k[8]),
                        "taker_buy_base_volume": float(k[9]),
                        "taker_buy_quote_volume": float(k[10]),
                    }
                )

            if rows:
                stmt = (
                    pg_insert(PriceCandle)
                    .values(rows)
                    .on_conflict_do_nothing(index_elements=["open_time"])
                )
                result = await session.execute(stmt)
                await session.commit()
                inserted += result.rowcount if result.rowcount is not None else len(rows)

            last_open_ms = int(klines[-1][0])
            next_cursor = last_open_ms + ONE_MINUTE_MS
            if next_cursor <= cursor_ms:
                break
            cursor_ms = next_cursor

            logger.info(
                "Backfill batch %d: fetched %d klines, cursor=%s",
                batches,
                len(klines),
                datetime.fromtimestamp(cursor_ms / 1000, tz=timezone.utc).isoformat(),
            )

    final_count = await count_candles_since(session, cutoff)
    oldest = await session.execute(
        select(func.min(PriceCandle.open_time)).where(PriceCandle.open_time >= cutoff)
    )
    newest = await session.execute(
        select(func.max(PriceCandle.open_time)).where(PriceCandle.open_time >= cutoff)
    )
    oldest_ts = oldest.scalar_one()
    newest_ts = newest.scalar_one()

    return {
        "status": "ok" if final_count >= target else "partial",
        "days_requested": days,
        "candles_in_window": final_count,
        "target_candles": target,
        "inserted": inserted,
        "batches_fetched": batches,
        "oldest_in_window": oldest_ts.isoformat() if oldest_ts else None,
        "newest_in_window": newest_ts.isoformat() if newest_ts else None,
    }
