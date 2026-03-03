FROM node:20-alpine AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --omit=dev

FROM node:20-alpine AS builder
WORKDIR /app
COPY frontend/ ./
COPY --from=deps /app/node_modules ./node_modules
# NEXT_PUBLIC_API_URL must be set as Railway env var at build time
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public 2>/dev/null || true

EXPOSE 3000
# Railway injects $PORT — Next.js standalone reads it automatically
ENV PORT=${PORT:-3000}
ENV HOSTNAME="0.0.0.0"
CMD ["node", "server.js"]
