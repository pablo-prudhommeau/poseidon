FROM node:20-alpine AS build-frontend
WORKDIR /app
ENV CI=1
RUN corepack enable

COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build -- --configuration=production

FROM nginx:alpine AS frontend
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=build-frontend /app/dist/frontend/browser/ /usr/share/nginx/html/

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
