# --- stage 1: build ----------------------------------------------------------
FROM node:20-alpine AS builder
WORKDIR /app

# Install deps first (cached layer)
COPY package.json package-lock.json* ./
RUN npm install

# Build
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
