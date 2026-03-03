'use client';
import { useState } from 'react';

type CalcMode = 'options' | 'pnl' | 'position';

export default function CalculoPage() {
    const [mode, setMode] = useState<CalcMode>('options');

    // Options P&L calculator state
    const [spot, setSpot] = useState(500);
    const [strike, setStrike] = useState(500);
    const [premium, setPremium] = useState(5);
    const [qty, setQty] = useState(1);
    const [optType, setOptType] = useState<'call' | 'put'>('call');
    const [targetPrice, setTargetPrice] = useState(510);

    const intrinsic = optType === 'call'
        ? Math.max(0, targetPrice - strike)
        : Math.max(0, strike - targetPrice);
    const pnl = (intrinsic - premium) * qty * 100;
    const breakeven = optType === 'call' ? strike + premium : strike - premium;

    return (
        <div className="space-y-6 max-w-4xl mx-auto">
            <div>
                <h1 className="text-2xl font-bold text-scanner-text">Calculo</h1>
                <p className="text-scanner-muted text-sm mt-1">Options P&amp;L, position sizing and risk calculators</p>
            </div>

            {/* Mode selector */}
            <div className="flex gap-2">
                {(['options', 'pnl', 'position'] as CalcMode[]).map((m) => (
                    <button
                        key={m}
                        onClick={() => setMode(m)}
                        className={`px-4 py-2 rounded-lg text-sm font-medium capitalize transition-colors ${mode === m
                                ? 'bg-scanner-accent/20 text-accent border border-scanner-accent/40'
                                : 'text-scanner-muted hover:text-scanner-text bg-scanner-surface border border-scanner-border'
                            }`}
                    >
                        {m === 'options' ? 'Options P&L' : m === 'pnl' ? 'Break-even' : 'Position Size'}
                    </button>
                ))}
            </div>

            {mode === 'options' && (
                <div className="grid md:grid-cols-2 gap-6">
                    {/* Inputs */}
                    <div className="bg-scanner-surface border border-scanner-border rounded-xl p-5 space-y-4">
                        <h2 className="text-sm font-semibold text-scanner-text uppercase tracking-wider">Parameters</h2>

                        <div className="flex gap-3">
                            {(['call', 'put'] as const).map((t) => (
                                <button key={t} onClick={() => setOptType(t)}
                                    className={`flex-1 py-2 rounded-lg text-sm font-semibold capitalize transition-colors ${optType === t ? (t === 'call' ? 'bg-green/20 text-green border border-green/40' : 'bg-red-900/30 text-red border border-red/40')
                                            : 'text-scanner-muted bg-scanner-bg border border-scanner-border'
                                        }`}
                                >{t}</button>
                            ))}
                        </div>

                        {[
                            { label: 'Spot Price', value: spot, set: setSpot },
                            { label: 'Strike Price', value: strike, set: setStrike },
                            { label: 'Premium Paid', value: premium, set: setPremium },
                            { label: 'Contracts (qty)', value: qty, set: setQty },
                            { label: 'Target Price', value: targetPrice, set: setTargetPrice },
                        ].map(({ label, value, set }) => (
                            <div key={label}>
                                <label className="block text-xs text-scanner-muted mb-1">{label}</label>
                                <input
                                    type="number"
                                    value={value}
                                    onChange={(e) => set(parseFloat(e.target.value) || 0)}
                                    step="0.5"
                                    className="w-full bg-scanner-bg border border-scanner-border text-scanner-text rounded-lg px-4 py-2 text-sm font-mono focus:outline-none focus:border-scanner-accent"
                                />
                            </div>
                        ))}
                    </div>

                    {/* Results */}
                    <div className="bg-scanner-surface border border-scanner-border rounded-xl p-5 space-y-4">
                        <h2 className="text-sm font-semibold text-scanner-text uppercase tracking-wider">Results</h2>

                        {[
                            { label: 'Intrinsic Value', value: `$${intrinsic.toFixed(2)}`, color: 'text-scanner-text' },
                            { label: 'Cost Basis', value: `$${(premium * qty * 100).toFixed(2)}`, color: 'text-scanner-muted' },
                            { label: 'Break-even', value: `$${breakeven.toFixed(2)}`, color: 'text-yellow' },
                            {
                                label: 'P&L at Target',
                                value: `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`,
                                color: pnl >= 0 ? 'text-green' : 'text-red',
                            },
                            {
                                label: 'Return %',
                                value: premium > 0 ? `${((pnl / (premium * qty * 100)) * 100).toFixed(1)}%` : '—',
                                color: pnl >= 0 ? 'text-green' : 'text-red',
                            },
                        ].map(({ label, value, color }) => (
                            <div key={label} className="flex justify-between items-center py-2 border-b border-scanner-border/40">
                                <span className="text-sm text-scanner-muted">{label}</span>
                                <span className={`text-xl font-mono font-bold ${color}`}>{value}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {mode !== 'options' && (
                <div className="bg-scanner-surface border border-scanner-border rounded-xl p-12 flex flex-col items-center text-center">
                    <p className="text-scanner-muted text-sm">
                        {mode === 'pnl' ? 'Break-even analysis' : 'Position sizing'} calculator — coming soon.
                    </p>
                </div>
            )}
        </div>
    );
}
