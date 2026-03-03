/** @type {import('next').NextConfig} */
const nextConfig = {
    reactStrictMode: true,
    output: 'standalone', // required for Docker multi-stage build
    async rewrites() {
        // In dev, proxy /api/* to FastAPI backend
        const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
        return [
            {
                source: '/api/:path*',
                destination: `${backendUrl}/api/:path*`,
            },
        ];
    },
    images: {
        remotePatterns: [],
    },
};

module.exports = nextConfig;
