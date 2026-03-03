import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
    title: 'SCANNER v2',
    description: 'Market analysis platform – Options, Screener, Macro, Market Maker',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
    return (
        <html lang="en" className="dark">
            <body className="antialiased">{children}</body>
        </html>
    );
}
