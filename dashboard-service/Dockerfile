# Etapa 1: compilar la app React con Vite
FROM node:20-alpine AS build

WORKDIR /app

# Copiar primero los manifests para aprovechar la caché de Docker
COPY package.json package-lock.json ./
RUN npm ci

# Copiar el código fuente y compilar
COPY vite.config.js index.html ./
COPY src ./src
RUN npm run build

# Etapa 2: servir los estáticos y hacer de reverse proxy con nginx
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 3000

# Verificación de salud del contenedor vía el endpoint /health de nginx
# (127.0.0.1 explícito: "localhost" resuelve primero a ::1 en este entorno y
# nginx solo escucha en 0.0.0.0, no en el wildcard IPv6)
HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=10s \
    CMD wget --spider -q http://127.0.0.1:3000/health || exit 1
