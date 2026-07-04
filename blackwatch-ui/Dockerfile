# --- stage 1: build ----------------------------------------------------------
FROM node:20-alpine AS builder
WORKDIR /app

# Install deps first (cached layer)
COPY package.json package-lock.json* ./
RUN npm install

# Build. IMPORTANT: rewrites() in next.config.mjs is evaluated at BUILD time
# and the result is baked into the standalone manifest. So BW_API_URL must be
# available here, not just at runtime. If it's unset the fallback baked in is
# localhost:8000 — which breaks the /api/* proxy inside docker-compose because
# the FastAPI service is reachable as `app:8000`, not `localhost:8000`.
ARG BW_API_URL=http://app:8000
ENV BW_API_URL=${BW_API_URL}
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# --- stage 2: runtime --------------------------------------------------------
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
ENV NEXT_TELEMETRY_DISABLED=1

# Standalone output bundles only what's needed
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
