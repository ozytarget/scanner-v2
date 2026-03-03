'use client';
import useSWR from 'swr';
import { api } from '@/lib/api';

const WATCHLIST = ['SPY', 'QQQ', 'DIA', 'IWM', 'AAPL', 'NVDA', 'TSLA', 'MSFT', 'AMZN', 'META'];

async function fetchQuotes() {
    const { data } = await api.get('/api/options/quote', { params: { ticker: 'SPY' } });
    return data;
}

export default function MetricsPage() {
    return (
        <div className="space-y-6 max-w-6xl mx-auto">
            <div>
                <h1 className="text-2xl font-bold text-scanner-text">Metrics</h1>
                <p className="text-scanner-muted text-sm mt-1">Market metrics, VIX, sector performance &amp; macro indicators</p>
            </div>

            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {[
                    { label: 'VIX', value: '—', desc: 'Volatility Index', color: 'text-yellow' },
                    { label: 'SPY', value: '—', desc: 'S&P 500 ETF', color: 'text-green' },
                    { label: 'QQQ', value: '—', desc: 'Nasdaq 100 ETF', color: 'text-accent' },
                    { label: 'DXY', value: '—', desc: 'US Dollar Index', color: 'text-scanner-text' },
                    { label: '10Y Yield', value: '—', desc: 'US Treasury 10Y', color: 'text-scanner-text' },
                    { label: 'GOLD', value: '—', desc: 'Gold (GLD)', color: 'text-yellow' },
                ].map((m) => (
                    <div key={m.label} className="bg-scanner-surface border border-scanner-border rounded-xl p-5">
                        <p className="text-xs text-scanner-muted uppercase tracking-wider">{m.desc}</p>
                        <p className="text-3xl font-mono font-bold mt-1 mb-0.5">
                            <span className={m.color}>{m.value}</span>
                        </p>
                        <p className="text-xl font-mono font-semibold text-scanner-muted">{m.label}</p>
                    </div>
                ))}
            </div>

            <div className="bg-scanner-surface border border-scanner-border rounded-xl p-8 flex flex-col items-center text-center">
                <p className="text-scanner-muted text-sm max-w-md">
                    Full metrics integration (sector heat map, macro dashboard, put/call ratios across indices)
                    is in progress. This tab maps to <strong className="text-scanner-text">Tab 6 – Metrics</strong> from
                    the Streamlit app.
                </p>
            </div>
        </div>
    );
}
