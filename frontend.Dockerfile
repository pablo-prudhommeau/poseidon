# ===== Build Angular =====
FROM node:20-alpine AS build-frontend
WORKDIR /app
ENV CI=1
RUN corepack enable

COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# (garde ton script si différent)
RUN npm run build -- --configuration=production

# ===== Nginx static =====
FROM nginx:alpine AS frontend
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf

# >>> ICI: ne copie QUE le dossier browser <<<
# si ton projet Angular s’appelle "frontend", la sortie est dist/frontend/browser
COPY --from=build-frontend /app/dist/frontend/browser/ /usr/share/nginx/html/

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
