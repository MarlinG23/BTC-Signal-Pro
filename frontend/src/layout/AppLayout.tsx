/**
 * Persistent chrome around category pages: live price header + tab nav.
 * The WebSocket stays in LiveDataProvider above this layout.
 */

import { Outlet } from "react-router-dom";
import { useLiveData } from "../context/LiveDataContext";
import { PriceHeader } from "../components/PriceHeader";
import { DesktopTabNav, MobileTabNav } from "../components/TabNav";

export function AppLayout() {
  const { livePrice, connected, candleCount } = useLiveData();

  return (
    <div className="min-h-screen bg-brand-dark">
      <header className="sticky top-0 z-30 border-b border-brand-border bg-brand-dark/95 backdrop-blur">
        <div className="max-w-7xl mx-auto px-4 pt-4 pb-3">
          <PriceHeader
            price={livePrice}
            connected={connected}
            candles={candleCount}
          />
          <DesktopTabNav />
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-6 pb-24 md:pb-8">
        <Outlet />
      </main>

      <MobileTabNav />
    </div>
  );
}
