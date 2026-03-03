import { Navbar } from '@/components/Navbar';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
    return (
        <div className="min-h-screen flex flex-col bg-scanner-bg">
            <Navbar />
            <main className="flex-1 p-4 md:p-6 animate-fade-in">{children}</main>
        </div>
    );
}
