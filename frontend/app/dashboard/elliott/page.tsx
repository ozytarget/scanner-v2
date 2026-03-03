'use client';

export default function ElliottPage() {
    return (
        <div className="space-y-6 max-w-5xl mx-auto">
            <div>
                <h1 className="text-2xl font-bold text-scanner-text">
                    Elliott Pulse<span className="text-accent">®</span>
                </h1>
                <p className="text-scanner-muted text-sm mt-1">Elliott Wave pattern detection &amp; impulse tracking</p>
            </div>
            <div className="bg-scanner-surface border border-scanner-border rounded-xl p-12 flex flex-col items-center justify-center text-center">
                <div className="text-5xl mb-4">〰️</div>
                <h2 className="text-lg font-semibold text-scanner-text mb-2">Elliott Pulse® — Coming Soon</h2>
                <p className="text-scanner-muted text-sm max-w-md">
                    This module is being ported from the Streamlit app. It will include automated Elliott Wave
                    detection, impulse/corrective pattern classification, and TradingView charting integration.
                </p>
            </div>
        </div>
    );
}
