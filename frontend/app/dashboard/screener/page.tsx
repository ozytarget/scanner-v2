'use client';
import { useState } from 'react';
import useSWR from 'swr';
import { runScreener } from '@/lib/api';

const SECTORS = ['Technology', 'Healthcare', 'Financial Services', 'Consumer Cyclical', 'Industrials', 'Energy', 'Communication Services', 'Consumer Defensive', 'Utilities', 'Real Estate', 'Basic Materials'];

export default function ScreenerPage() {
    const [params, setParams] = useState({
        sector: '',
        market_cap_min: '',
        market_cap_max: '',
        volume_min: '',
        limit: 50,
    });
    const [query, setQuery] = useState<Record<string, unknown> | null>(null);

    const { data, isLoading } = useSWR(
        query ? ['screener', JSON.stringify(query)] : null,
        () => runScreener(query!)
    );

    const handleSearch = (e: React.FormEvent) => {
        e.preventDefault();
        const q: Record<string, unknown> = { limit: params.limit };
        if (params.sector) q.sector = params.sector;
        if (params.market_cap_min) q.market_cap_min = parseFloat(params.market_cap_min) * 1e9;
        if (params.market_cap_max) q.market_cap_max = parseFloat(params.market_cap_max) * 1e9;
        if (params.volume_min) q.volume_min = parseInt(params.volume_min);
        setQuery(q);
    };

    return (
        <div className="space-y-6 max-w-7xl mx-auto">
            <div>
                <h1 className="text-2xl font-bold text-scanner-text">Market Scanner</h1>
                <p className="text-scanner-muted text-sm mt-1">Filter stocks by sector, market cap, volume</p>
            </div>

            <form onSubmit={handleSearch} className="bg-scanner-surface border border-scanner-border rounded-xl p-5 flex flex-wrap gap-4 items-end">
                <div>
                    <label className="block text-xs text-scanner-muted mb-1 uppercase tracking-wider">Sector</label>
                    <select
                        value={params.sector}
                        onChange={(e) => setParams({ ...params, sector: e.target.value })}
                        className="bg-scanner-bg border border-scanner-border text-scanner-text rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-scanner-accent"
                    >
                        <option value="">All Sectors</option>
                        {SECTORS.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                </div>
                <div>
                    <label className="block text-xs text-scanner-muted mb-1 uppercase tracking-wider">MCap Min ($B)</label>
                    <input type="number" placeholder="e.g. 1" value={params.market_cap_min}
                        onChange={(e) => setParams({ ...params, market_cap_min: e.target.value })}
                        className="bg-scanner-bg border border-scanner-border text-scanner-text rounded-lg px-3 py-2 text-sm w-28 focus:outline-none focus:border-scanner-accent"
                    />
                </div>
                <div>
                    <label className="block text-xs text-scanner-muted mb-1 uppercase tracking-wider">MCap Max ($B)</label>
                    <input type="number" placeholder="e.g. 100" value={params.market_cap_max}
                        onChange={(e) => setParams({ ...params, market_cap_max: e.target.value })}
                        className="bg-scanner-bg border border-scanner-border text-scanner-text rounded-lg px-3 py-2 text-sm w-28 focus:outline-none focus:border-scanner-accent"
                    />
                </div>
                <div>
                    <label className="block text-xs text-scanner-muted mb-1 uppercase tracking-wider">Min Volume</label>
                    <input type="number" placeholder="e.g. 500000" value={params.volume_min}
                        onChange={(e) => setParams({ ...params, volume_min: e.target.value })}
                        className="bg-scanner-bg border border-scanner-border text-scanner-text rounded-lg px-3 py-2 text-sm w-36 focus:outline-none focus:border-scanner-accent"
                    />
                </div>
                <div>
                    <label className="block text-xs text-scanner-muted mb-1 uppercase tracking-wider">Limit</label>
                    <select value={params.limit} onChange={(e) => setParams({ ...params, limit: parseInt(e.target.value) })}
                        className="bg-scanner-bg border border-scanner-border text-scanner-text rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-scanner-accent"
                    >
                        {[25, 50, 100, 200].map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                </div>
                <button type="submit" className="bg-scanner-accent text-scanner-bg font-semibold px-5 py-2 rounded-lg text-sm hover:bg-scanner-accentDim transition-colors">
                    Scan
                </button>
            </form>

            {isLoading && <div className="text-scanner-muted text-sm animate-pulse">Scanning…</div>}

            {data && (
                <div className="bg-scanner-surface border border-scanner-border rounded-xl overflow-hidden">
                    <div className="px-5 py-3 border-b border-scanner-border flex justify-between items-center">
                        <span className="text-sm font-semibold text-scanner-text">{data.length} results</span>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full text-xs font-mono">
                            <thead>
                                <tr className="text-scanner-muted border-b border-scanner-border">
                                    {['Symbol', 'Company', 'Price', 'Change %', 'Market Cap', 'Volume', 'Sector'].map((h) => (
                                        <th key={h} className="px-4 py-3 text-left font-medium uppercase tracking-wider">{h}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {data.map((row: Record<string, unknown>, i: number) => {
                                    const chg = row.changesPercentage as number;
                                    return (
                                        <tr key={i} className="border-b border-scanner-border/40 hover:bg-white/5 transition-colors">
                                            <td className="px-4 py-3 font-bold text-accent">{String(row.symbol)}</td>
                                            <td className="px-4 py-3 text-scanner-text max-w-[160px] truncate">{String(row.companyName)}</td>
                                            <td className="px-4 py-3 text-scanner-text">${Number(row.price).toFixed(2)}</td>
                                            <td className={`px-4 py-3 ${chg >= 0 ? 'text-green' : 'text-red'}`}>
                                                {chg >= 0 ? '+' : ''}{chg?.toFixed(2)}%
                                            </td>
                                            <td className="px-4 py-3 text-scanner-muted">
                                                {row.marketCap ? `$${(Number(row.marketCap) / 1e9).toFixed(1)}B` : '—'}
                                            </td>
                                            <td className="px-4 py-3 text-scanner-muted">{Number(row.volume).toLocaleString()}</td>
                                            <td className="px-4 py-3 text-scanner-muted">{String(row.sector || '—')}</td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
}
