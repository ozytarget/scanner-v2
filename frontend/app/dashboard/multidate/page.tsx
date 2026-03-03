'use client';

export default function MultiDatePage() {
    return (
        <div className="space-y-6 max-w-6xl mx-auto">
            <div>
                <h1 className="text-2xl font-bold text-scanner-text">Multi-Date Options</h1>
                <p className="text-scanner-muted text-sm mt-1">Compare open interest across multiple expirations simultaneously</p>
            </div>
            <div className="bg-scanner-surface border border-scanner-border rounded-xl p-12 flex flex-col items-center justify-center text-center">
                <div className="text-5xl mb-4">📅</div>
                <h2 className="text-lg font-semibold text-scanner-text mb-2">Multi-Date Options — Coming Soon</h2>
                <p className="text-scanner-muted text-sm max-w-md">
                    This module will allow you to load options chains for multiple expirations at once
                    and overlay Max Pain levels + GEX on a single chart for expiration-to-expiration comparison.
                </p>
            </div>
        </div>
    );
}
