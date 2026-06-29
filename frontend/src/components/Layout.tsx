import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  CheckSquare,
  FolderKanban,
  type LucideIcon,
  Menu,
  MessageSquare,
  Mountain,
  Sparkles,
  X,
} from 'lucide-react';
import { cn } from '../lib/cn';
import { Badge } from './ui/Badge';
import { HealthPill } from './domain/HealthPill';

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

const NAV: NavItem[] = [
  { to: '/', label: 'Проєкти', icon: FolderKanban, end: true },
  { to: '/approvals', label: 'Черга дій', icon: CheckSquare },
];

const SOON: { label: string; icon: LucideIcon }[] = [
  { label: 'Резюме', icon: Sparkles },
  { label: 'Запитати', icon: MessageSquare },
];

function BrandMark() {
  return (
    <div className="flex items-center gap-2 px-2">
      <span className="flex h-8 w-8 items-center justify-center rounded-card bg-brand/15 text-brand">
        <Mountain className="h-5 w-5" aria-hidden="true" />
      </span>
      <span className="text-base font-semibold tracking-tight text-fg">Cairnwise</span>
    </div>
  );
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex flex-1 flex-col gap-1 px-3 py-4">
      {NAV.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-card px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-surface-2 text-fg'
                  : 'text-muted hover:bg-surface-2 hover:text-fg',
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
            {item.label}
          </NavLink>
        );
      })}

      <div className="mt-4 px-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
          AI · Скоро
        </p>
        <div className="flex flex-col gap-1">
          {SOON.map((item) => {
            const Icon = item.icon;
            return (
              <div
                key={item.label}
                aria-disabled="true"
                className="flex cursor-not-allowed items-center gap-3 rounded-card px-0 py-2 text-sm text-muted/70"
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span className="flex-1">{item.label}</span>
                <Badge tone="neutral">Скоро</Badge>
              </div>
            );
          })}
        </div>
      </div>
    </nav>
  );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center border-b border-border px-3">
        <BrandMark />
      </div>
      <NavLinks onNavigate={onNavigate} />
    </div>
  );
}

export function Layout() {
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Scroll-lock the body while the mobile drawer is open.
  useEffect(() => {
    if (!drawerOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [drawerOpen]);

  return (
    <div className="grid min-h-screen grid-cols-1 grid-rows-[3.5rem_1fr] lg:grid-cols-[16rem_1fr]">
      {/* Sidebar — static at >= lg */}
      <aside className="row-span-2 hidden border-r border-border bg-surface lg:block">
        <SidebarContent />
      </aside>

      {/* Topbar */}
      <header className="col-start-1 flex h-14 items-center justify-between gap-3 border-b border-border bg-surface px-4 lg:col-start-2">
        <div className="flex items-center gap-3">
          <button
            type="button"
            aria-label="Відкрити меню"
            onClick={() => setDrawerOpen(true)}
            className="rounded-card p-2 text-muted transition-colors hover:bg-surface-2 hover:text-fg lg:hidden"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="lg:hidden">
            <BrandMark />
          </div>
        </div>
        <HealthPill />
      </header>

      {/* Main content */}
      <main className="col-start-1 overflow-y-auto lg:col-start-2">
        <div className="mx-auto max-w-6xl px-6 py-6">
          <Outlet />
        </div>
      </main>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setDrawerOpen(false)}
            aria-hidden="true"
          />
          <div className="absolute inset-y-0 left-0 w-64 border-r border-border bg-surface shadow-card">
            <button
              type="button"
              aria-label="Закрити меню"
              onClick={() => setDrawerOpen(false)}
              className="absolute right-2 top-3 z-10 rounded-card p-2 text-muted transition-colors hover:bg-surface-2 hover:text-fg"
            >
              <X className="h-5 w-5" />
            </button>
            <SidebarContent onNavigate={() => setDrawerOpen(false)} />
          </div>
        </div>
      )}
    </div>
  );
}

export default Layout;
