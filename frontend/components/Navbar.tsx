'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuthStore } from '@/lib/auth';
import {
    BarChart2,
    Newspaper,
    TrendingUp,
    Activity,
    LayoutDashboard,
    Calculator,
    CalendarRange,
    LogOut,
    User,
} from 'lucide-react';
import { clsx } from 'clsx';

const tabs = [
    { label: 'Gummy Bubbles®', href: '/dashboard/options', icon: Activity },
    { label: 'Market Scanner', href: '/dashboard/screener', icon: BarChart2 },
    { label: 'News', href: '/dashboard/news', icon: Newspaper },
    { label: 'Analyst Flow', href: '/dashboard/analyst', icon: TrendingUp },
    { label: 'Elliott Pulse®', href: '/dashboard/elliott', icon: LayoutDashboard },
    { label: 'Metrics', href: '/dashboard/metrics', icon: LayoutDashboard },
    { label: 'Multi-Date', href: '/dashboard/multidate', icon: CalendarRange },
    { label: 'Calculo', href: '/dashboard/calculo', icon: Calculator },
];

export function Navbar() {
    const pathname = usePathname();
    const { user, logout } = useAuthStore();

    return (
        <header className="sticky top-0 z-50 bg-scanner-surface/90 backdrop-blur border-b border-scanner-border">
            <div className="flex items-center justify-between px-4 h-14">
                {/* Logo */}
                <Link href="/dashboard/options" className="font-mono font-bold text-xl text-accent tracking-widest hover:opacity-80 transition-opacity">
                    SCANNER
                    <span className="text-xs text-scanner-muted ml-1">v2</span>
                </Link>

                {/* Tabs */}
                <nav className="hidden lg:flex items-center gap-1 overflow-x-auto">
                    {tabs.map((tab) => {
                        const Icon = tab.icon;
                        const active = pathname === tab.href;
                        return (
                            <Link
                                key={tab.href}
                                href={tab.href}
                                className={clsx(
                                    'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap',
                                    active
                                        ? 'bg-scanner-accent/20 text-accent border border-scanner-accent/40'
                                        : 'text-scanner-muted hover:text-scanner-text hover:bg-white/5'
                                )}
                            >
                                <Icon size={13} />
                                {tab.label}
                            </Link>
                        );
                    })}
                </nav>

                {/* User */}
                <div className="flex items-center gap-3">
                    {user && (
                        <div className="flex items-center gap-2 text-xs text-scanner-muted">
                            <User size={13} />
                            <span className="hidden sm:inline">{user.username}</span>
                            <span className={clsx(
                                'px-1.5 py-0.5 rounded text-[10px] font-mono uppercase',
                                user.tier === 'elite' ? 'bg-purple-900/50 text-purple-300' :
                                    user.tier === 'pro' ? 'bg-blue-900/50 text-blue-300' :
                                        'bg-gray-800 text-gray-400'
                            )}>
                                {user.tier}
                            </span>
                        </div>
                    )}
                    <button
                        onClick={logout}
                        className="text-scanner-muted hover:text-scanner-red transition-colors"
                        title="Sign out"
                    >
                        <LogOut size={15} />
                    </button>
                </div>
            </div>

            {/* Mobile tabs */}
            <nav className="lg:hidden flex overflow-x-auto gap-1 px-4 pb-2">
                {tabs.map((tab) => {
                    const active = pathname === tab.href;
                    return (
                        <Link
                            key={tab.href}
                            href={tab.href}
                            className={clsx(
                                'px-3 py-1 rounded text-xs whitespace-nowrap transition-colors',
                                active
                                    ? 'bg-scanner-accent/20 text-accent'
                                    : 'text-scanner-muted hover:text-scanner-text'
                            )}
                        >
                            {tab.label}
                        </Link>
                    );
                })}
            </nav>
        </header>
    );
}
