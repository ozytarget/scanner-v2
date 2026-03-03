'use client';
import { useState } from 'react';
import useSWR from 'swr';
import { getNews } from '@/lib/api';

export default function NewsPage() {
    const [tickers, setTickers] = useState('SPY,QQQ,AAPL,NVDA');
    const [tickerInput, setTickerInput] = useState('SPY,QQQ,AAPL,NVDA');

    const { data, isLoading } = useSWR(
        ['news', tickers],
        () => getNews(tickers, 30),
        { refreshInterval: 60_000 }
    );

    return (
        <div className="space-y-6 max-w-5xl mx-auto">
            <div>
                <h1 className="text-2xl font-bold text-scanner-text">News Feed</h1>
                <p className="text-scanner-muted text-sm mt-1">Latest headlines — auto-refreshes every minute</p>
            </div>

            <form
                onSubmit={(e) => { e.preventDefault(); setTickers(tickerInput); }}
                className="flex gap-3"
            >
                <input
                    value={tickerInput}
                    onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
                    placeholder="SPY,QQQ,AAPL"
                    className="flex-1 max-w-xs bg-scanner-surface border border-scanner-border text-scanner-text rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-scanner-accent"
                />
                <button type="submit" className="bg-scanner-accent text-scanner-bg font-semibold px-5 py-2 rounded-lg text-sm hover:bg-scanner-accentDim transition-colors">
                    Update
                </button>
            </form>

            {isLoading && <div className="text-scanner-muted text-sm animate-pulse">Loading news…</div>}

            <div className="space-y-3">
                {(data || []).map((item: Record<string, unknown>, i: number) => (
                    <a
                        key={i}
                        href={String(item.url)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block bg-scanner-surface border border-scanner-border rounded-xl p-4 hover:border-scanner-accent/50 transition-colors group"
                    >
                        <div className="flex items-start justify-between gap-4">
                            <div className="flex-1 min-w-0">
                                <p className="text-sm font-semibold text-scanner-text group-hover:text-accent transition-colors line-clamp-2">
                                    {String(item.title)}
                                </p>
                                <p className="text-xs text-scanner-muted mt-1 line-clamp-2">{String(item.text || '')}</p>
                            </div>
                            {Boolean(item.image) && (
                                // eslint-disable-next-line @next/next/no-img-element
                                <img src={String(item.image)} alt="" className="w-20 h-14 object-cover rounded-lg shrink-0" />
                            )}
                        </div>
                        <div className="flex items-center gap-3 mt-2 text-[11px] text-scanner-muted">
                            <span>{String(item.publishedDate || '').slice(0, 16)}</span>
                            <span>·</span>
                            <span>{String(item.site || '')}</span>
                            {Boolean(item.symbol) && (
                                <>
                                    <span>·</span>
                                    <span className="text-accent font-mono">{String(item.symbol)}</span>
                                </>
                            )}
                        </div>
                    </a>
                ))}
            </div>
        </div>
    );
}
