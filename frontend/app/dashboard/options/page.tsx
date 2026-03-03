'use client';
import { useState } from 'react';
import useSWR from 'swr';
import { getExpirations, getOptionsAnalysis } from '@/lib/api';

// ─── Simple bar chart via SVG ─────────────────────────────────────────────────
function OIBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
    const pct = max > 0 ? (value / max) * 100 : 0;
    return (
        <div className="flex items-center gap-2 text-xs font-mono">
            <span className="w-14 text-right text-scanner-muted shrink-0">{label}</span>
            <div className="flex-1 h-4 bg-scanner-bg rounded overflow-hidden">
                <div
                    className="h-full rounded transition-all duration-300"
                    style={{ width: `${pct}%`, backgroundColor: color }}
                />
            </div>
            <span className="w-16 text-scanner-muted shrink-0">{value.toLocaleString()}</span>
        </div>
    );
}

export default function OptionsPage() {
    const [ticker, setTicker] = useState('SPY');
    const [tickerInput, setTickerInput] = useState('SPY');
    const [expiration, setExpiration] = useState('');

    const { data: expData, isLoading: expLoading } = useSWR(
        ticker ? `/expirations/${ticker}` : null,
        () => getExpirations(ticker),
        { onSuccess: (d) => { if (d.expirations?.length && !expiration) setExpiration(d.expirations[0]); } }
    );

    const { data: analysis, isLoading: analysisLoading } = useSWR(
        ticker && expiration ? `/analysis/${ticker}/${expiration}` : null,
        () => getOptionsAnalysis(ticker, expiration)
    );

    const handleSearch = (e: React.FormEvent) => {
        e.preventDefault();
        setTicker(tickerInput.trim().toUpperCase());
        setExpiration('');
    };

    const maxOI = analysis
        ? Math.max(...(analysis.call_oi || []), ...(analysis.put_oi || []), 1)
        : 1;

    return (
        <div className="space-y-6 max-w-6xl mx-auto">
            <div>
                <h1 className="text-2xl font-bold text-scanner-text">
                    Gummy Data Bubbles<span className="text-accent">®</span>
                </h1>
                <p className="text-scanner-muted text-sm mt-1">Options open interest, Max Pain &amp; GEX analysis</p>
            </div>

            {/* Controls */}
            <form onSubmit={handleSearch} className="flex flex-wrap gap-3 items-end">
                <div>
                    <label className="block text-xs text-scanner-muted mb-1 uppercase tracking-wider">Ticker</label>
                    <input
                        value={tickerInput}
                        onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
                        className="bg-scanner-surface border border-scanner-border text-scanner-text rounded-lg px-4 py-2 text-sm w-28 focus:outline-none focus:border-scanner-accent"
                        placeholder="SPY"
                    />
                </div>
                {expData?.expirations && (
                    <div>
                        <label className="block text-xs text-scanner-muted mb-1 uppercase tracking-wider">Expiration</label>
                        <select
                            value={expiration}
                            onChange={(e) => setExpiration(e.target.value)}
                            className="bg-scanner-surface border border-scanner-border text-scanner-text rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-scanner-accent"
                        >
                            {expData.expirations.map((d: string) => (
                                <option key={d} value={d}>{d}</option>
                            ))}
                        </select>
                    </div>
                )}
                <button
                    type="submit"
                    className="bg-scanner-accent text-scanner-bg font-semibold px-5 py-2 rounded-lg text-sm hover:bg-scanner-accentDim transition-colors"
                >
                    Analyze
                </button>
            </form>

            {(expLoading || analysisLoading) && (
                <div className="text-scanner-muted text-sm animate-pulse">Loading data…</div>
            )}

            {analysis && (
                <>
                    {/* Key Metrics */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                        {[
                            { label: 'Max Pain', value: `$${analysis.max_pain?.toFixed(2) ?? '—'}`, color: 'text-yellow' },
                            { label: 'Spot Price', value: `$${analysis.spot?.toFixed(2) ?? '—'}`, color: 'text-green' },
                            { label: 'OI Put/Call', value: analysis.pcr?.oi_pcr?.toFixed(3) ?? '—', color: 'text-accent' },
                            { label: 'Net GEX', value: analysis.gex?.total ? `${(analysis.gex.total / 1e6).toFixed(1)}M` : '—', color: analysis.gex?.total >= 0 ? 'text-green' : 'text-red' },
                        ].map((m) => (
                            <div key={m.label} className="bg-scanner-surface border border-scanner-border rounded-xl p-4">
                                <p className="text-xs text-scanner-muted uppercase tracking-wider mb-1">{m.label}</p>
                                <p className={`text-2xl font-mono font-bold ${m.color}`}>{m.value}</p>
                            </div>
                        ))}
                    </div>

                    {/* OI Chart */}
                    <div className="bg-scanner-surface border border-scanner-border rounded-xl p-5">
                        <h2 className="text-sm font-semibold text-scanner-text mb-4 uppercase tracking-wider">
                            Open Interest by Strike — {analysis.ticker} / {analysis.expiration}
                        </h2>
                        <div className="space-y-1.5 max-h-[480px] overflow-y-auto pr-2">
                            {analysis.strikes?.map((strike: number, i: number) => (
                                <div key={strike}>
                                    <p className="text-[10px] text-scanner-muted font-mono mb-0.5">${strike}</p>
                                    <OIBar label="Calls" value={analysis.call_oi[i]} max={maxOI} color="#00ff88" />
                                    <OIBar label="Puts" value={analysis.put_oi[i]} max={maxOI} color="#ff4466" />
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* GEX by Strike */}
                    {analysis.gex && Object.keys(analysis.gex).length > 1 && (
                        <div className="bg-scanner-surface border border-scanner-border rounded-xl p-5">
                            <h2 className="text-sm font-semibold text-scanner-text mb-4 uppercase tracking-wider">
                                Gamma Exposure (GEX) by Strike
                            </h2>
                            <div className="space-y-1 max-h-[360px] overflow-y-auto pr-2">
                                {Object.entries(analysis.gex)
                                    .filter(([k]) => k !== 'total')
                                    .sort(([a], [b]) => parseFloat(a) - parseFloat(b))
                                    .map(([strike, val]) => {
                                        const v = val as number;
                                        const maxG = Math.max(...Object.values(analysis.gex as Record<string, number>).filter((_, i, arr) => arr !== null).map(Math.abs), 1);
                                        return (
                                            <div key={strike} className="flex items-center gap-2 text-xs font-mono">
                                                <span className="w-14 text-right text-scanner-muted shrink-0">${strike}</span>
                                                <div className="flex-1 h-3 bg-scanner-bg rounded overflow-hidden relative">
                                                    <div
                                                        className="absolute top-0 h-full rounded"
                                                        style={{
                                                            width: `${(Math.abs(v) / maxG) * 50}%`,
                                                            left: v >= 0 ? '50%' : `${50 - (Math.abs(v) / maxG) * 50}%`,
                                                            backgroundColor: v >= 0 ? '#00ff88' : '#ff4466',
                                                        }}
                                                    />
                                                    <div className="absolute left-1/2 top-0 w-px h-full bg-scanner-border" />
                                                </div>
                                                <span className={`w-20 ${v >= 0 ? 'text-green' : 'text-red'}`}>
                                                    {(v / 1e6).toFixed(2)}M
                                                </span>
                                            </div>
                                        );
                                    })}
                            </div>
                        </div>
                    )}
                </>
            )}
        </div>
    );
}
