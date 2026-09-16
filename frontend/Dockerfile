# ==========================================
# Stage 1: Build React/Vite Frontend
# ==========================================
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# ==========================================
# Stage 2: Unprivileged Hardened Nginx
# ==========================================
FROM nginxinc/nginx-unprivileged:alpine AS runner

# Static production build files
COPY --from=builder /app/dist /usr/share/nginx/html

# Custom Nginx configuration with reverse proxy and /metrics blocking
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Port 8080 is standard for nginx-unprivileged
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://localhost:8080/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
