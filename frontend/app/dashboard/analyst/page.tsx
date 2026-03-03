'use client';
import { useState } from 'react';
import useSWR from 'swr';
import { getAnalystRatings, getPriceTargets } from '@/lib/api';

const RATING_COLOR: Record<string, string> = {
    'Strong Buy': 'text-green',
    Buy: 'text-green',
    'Outperform': 'text-accent',
    Hold: 'text-yellow',
    Sell: 'text-red',
    'Strong Sell': 'text-red',
    Underperform: 'text-red',
};

export default function AnalystPage() {
    const [ticker, setTicker] = useState('AAPL');
    const [tickerInput, setTickerInput] = useState('AAPL');

    const { data: ratings, isLoading: ratingsLoading } = useSWR(
        ['analyst-ratings', ticker],
        () => getAnalystRatings(ticker)
    );
    const { data: targets, isLoading: targetsLoading } = useSWR(
        ['price-targets', ticker],
        () => getPriceTargets(ticker)
    );

    const handleSearch = (e: React.FormEvent) => {
        e.preventDefault();
        setTicker(tickerInput.trim().toUpperCase());
    };

    return (
        <div className="space-y-6 max-w-6xl mx-auto">
            <div>
                <h1 className="text-2xl font-bold text-scanner-text">Analyst Rating Flow</h1>
                <p className="text-scanner-muted text-sm mt-1">Buy/Hold/Sell ratings and price targets</p>
            </div>

            <form onSubmit={handleSearch} className="flex gap-3">
                <input
                    value={tickerInput}
                    onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
                    className="bg-scanner-surface border border-scanner-border text-scanner-text rounded-lg px-4 py-2 text-sm w-28 focus:outline-none focus:border-scanner-accent"
                    placeholder="AAPL"
                />
                <button type="submit" className="bg-scanner-accent text-scanner-bg font-semibold px-5 py-2 rounded-lg text-sm hover:bg-scanner-accentDim transition-colors">
                    Load
                </button>
            </form>

            <div className="grid lg:grid-cols-2 gap-6">
                {/* Ratings */}
                <div className="bg-scanner-surface border border-scanner-border rounded-xl overflow-hidden">
                    <div className="px-5 py-3 border-b border-scanner-border">
                        <h2 className="text-sm font-semibold text-scanner-text uppercase tracking-wider">Consensus Ratings</h2>
                    </div>
                    {ratingsLoading ? (
                        <div className="p-5 text-scanner-muted text-sm animate-pulse">Loading…</div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full text-xs font-mono">
                                <thead>
                                    <tr className="text-scanner-muted border-b border-scanner-border">
                                        <th className="px-4 py-3 text-left">Date</th>
                                        <th className="px-4 py-3 text-left">Analyst</th>
                                        <th className="px-4 py-3 text-left">Rating</th>
                                        <th className="px-4 py-3 text-right">Score</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {(ratings || []).slice(0, 20).map((r: Record<string, unknown>, i: number) => (
                                        <tr key={i} className="border-b border-scanner-border/40 hover:bg-white/5">
                                            <td className="px-4 py-2 text-scanner-muted">{String(r.date || '').slice(0, 10)}</td>
                                            <td className="px-4 py-2 text-scanner-text">{String(r.gradingCompany || '—')}</td>
                                            <td className={`px-4 py-2 ${RATING_COLOR[String(r.newGrade)] || 'text-scanner-muted'}`}>
                                                {String(r.newGrade || '—')}
                                            </td>
                                            <td className="px-4 py-2 text-right text-scanner-muted">{String(r.ratingScore || '—')}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>

                {/* Price Targets */}
                <div className="bg-scanner-surface border border-scanner-border rounded-xl overflow-hidden">
                    <div className="px-5 py-3 border-b border-scanner-border">
                        <h2 className="text-sm font-semibold text-scanner-text uppercase tracking-wider">Price Targets</h2>
                    </div>
                    {targetsLoading ? (
                        <div className="p-5 text-scanner-muted text-sm animate-pulse">Loading…</div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full text-xs font-mono">
                                <thead>
                                    <tr className="text-scanner-muted border-b border-scanner-border">
                                        <th className="px-4 py-3 text-left">Date</th>
                                        <th className="px-4 py-3 text-left">Analyst</th>
                                        <th className="px-4 py-3 text-right">Target</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {(targets || []).slice(0, 20).map((t: Record<string, unknown>, i: number) => (
                                        <tr key={i} className="border-b border-scanner-border/40 hover:bg-white/5">
                                            <td className="px-4 py-2 text-scanner-muted">{String(t.publishedDate || '').slice(0, 10)}</td>
                                            <td className="px-4 py-2 text-scanner-text">{String(t.analystCompany || t.analyst || '—')}</td>
                                            <td className="px-4 py-2 text-right text-accent">${Number(t.priceTarget || 0).toFixed(2)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
