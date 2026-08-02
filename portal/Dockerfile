FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci --include=optional
COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

FROM nginx:1.25-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD wget -q -O - http://127.0.0.1:8080/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
