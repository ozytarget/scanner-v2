'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/lib/auth';

export default function LoginPage() {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const login = useAuthStore((s) => s.login);
    const router = useRouter();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            await login(username, password);
            router.push('/dashboard/options');
        } catch (err: unknown) {
            const msg =
                (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
                'Invalid credentials';
            setError(msg);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-scanner-bg px-4">
            {/* Background grid */}
            <div
                className="fixed inset-0 opacity-[0.03] pointer-events-none"
                style={{
                    backgroundImage:
                        'repeating-linear-gradient(0deg, transparent, transparent 39px, #00d4ff 39px, #00d4ff 40px), repeating-linear-gradient(90deg, transparent, transparent 39px, #00d4ff 39px, #00d4ff 40px)',
                }}
            />

            <div className="relative w-full max-w-md">
                {/* Logo */}
                <div className="text-center mb-8">
                    <h1 className="text-4xl font-mono font-bold text-accent glow-accent tracking-widest">
                        SCANNER
                    </h1>
                    <p className="text-scanner-muted text-sm mt-2">v2.0 · Market Analysis Platform</p>
                </div>

                {/* Card */}
                <form
                    onSubmit={handleSubmit}
                    className="bg-scanner-surface border border-scanner-border rounded-2xl p-8 shadow-2xl"
                >
                    <h2 className="text-xl font-semibold text-scanner-text mb-6">Sign In</h2>

                    <div className="space-y-4">
                        <div>
                            <label className="block text-xs text-scanner-muted mb-1 uppercase tracking-wider">
                                Username
                            </label>
                            <input
                                type="text"
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                required
                                className="w-full bg-scanner-bg border border-scanner-border text-scanner-text rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-scanner-accent transition-colors"
                                placeholder="your_username"
                                autoComplete="username"
                            />
                        </div>

                        <div>
                            <label className="block text-xs text-scanner-muted mb-1 uppercase tracking-wider">
                                Password
                            </label>
                            <input
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                className="w-full bg-scanner-bg border border-scanner-border text-scanner-text rounded-lg px-4 py-3 text-sm focus:outline-none focus:border-scanner-accent transition-colors"
                                placeholder="••••••••"
                                autoComplete="current-password"
                            />
                        </div>

                        {error && (
                            <p className="text-scanner-red text-sm bg-red-950/30 border border-red-900/50 rounded-lg px-4 py-2">
                                {error}
                            </p>
                        )}

                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full bg-scanner-accent text-scanner-bg font-semibold py-3 rounded-lg hover:bg-scanner-accentDim disabled:opacity-50 disabled:cursor-not-allowed transition-colors mt-2"
                        >
                            {loading ? 'Signing in…' : 'Sign In'}
                        </button>
                    </div>
                </form>

                <p className="text-center text-scanner-muted text-xs mt-6">
                    SCANNER v2 · © {new Date().getFullYear()}
                </p>
            </div>
        </div>
    );
}
