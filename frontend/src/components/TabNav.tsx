/**
 * Category navigation — top tabs on desktop, bottom bar on mobile.
 * Lives in AppLayout so tab switches do not remount LiveDataProvider.
 */

import { NavLink } from "react-router-dom";
import clsx from "clsx";
import {
  Activity,
  BarChart2,
  Clock,
  FlaskConical,
  Newspaper,
} from "lucide-react";

export const TABS = [
  { to: "/", label: "Live", icon: Activity, end: true },
  { to: "/indicators", label: "Indicators", icon: BarChart2, end: false },
  { to: "/history", label: "History", icon: Clock, end: false },
  { to: "/news", label: "News", icon: Newspaper, end: false },
  { to: "/research", label: "Research", icon: FlaskConical, end: false },
] as const;

export function DesktopTabNav() {
  return (
    <nav
      className="mt-3 hidden md:flex items-center gap-1 border-t border-brand-border pt-3"
      aria-label="App categories"
    >
      {TABS.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            clsx(
              "flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
              isActive
                ? "bg-brand-green/15 text-brand-green border border-brand-green/30"
                : "text-brand-muted hover:text-white hover:bg-brand-border/40 border border-transparent"
            )
          }
        >
          <Icon className="w-4 h-4" />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

export function MobileTabNav() {
  return (
    <nav
      className="md:hidden fixed bottom-0 inset-x-0 z-40 border-t border-brand-border bg-brand-card/95 backdrop-blur pb-[env(safe-area-inset-bottom)]"
      aria-label="App categories"
    >
      <div className="grid grid-cols-5">
        {TABS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              clsx(
                "flex flex-col items-center justify-center gap-0.5 py-2.5 text-[10px] font-medium tracking-wide",
                isActive ? "text-brand-green" : "text-brand-muted"
              )
            }
          >
            <Icon className="w-5 h-5" />
            {label}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
