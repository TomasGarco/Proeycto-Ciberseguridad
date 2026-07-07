FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install --omit=dev

COPY index.js .

EXPOSE 8003

HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=10s \
    CMD node -e "require('http').get('http://localhost:8003/api/health', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "index.js"]
