# ── Atlas WDK Service — Railway / Docker deployment ──────────────────────────
# Railway injects PORT automatically; server.js reads process.env.PORT.
# For local Docker: docker build -t atlas-wdk . && docker run -p 3001:3001 atlas-wdk

FROM node:20-alpine

WORKDIR /app

# Install prod deps only (no devDependencies)
COPY package*.json ./
RUN npm install --omit=dev

# Copy service source
COPY server.js ./

# Health check — Railway uses this to decide when the service is ready
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- "http://localhost:${PORT:-3001}/health" || exit 1

CMD ["node", "server.js"]
