# Next.js standalone build. Same-origin deployment: leave NEXT_PUBLIC_API_BASE empty
# and route /api, /ws, /health to the API in the reverse proxy (infra/Caddyfile).
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE=""
# Railway passes this on GitHub deploys; it is baked into the bundle as the build id
ARG RAILWAY_GIT_COMMIT_SHA=""
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE NEXT_TELEMETRY_DISABLED=1 \
    RAILWAY_GIT_COMMIT_SHA=$RAILWAY_GIT_COMMIT_SHA
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
# HOSTNAME=:: listens dual-stack (IPv4+IPv6) for private networks such as Railway's
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=::
RUN addgroup -S app && adduser -S app -G app
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER app
EXPOSE 3000
CMD ["node", "server.js"]
