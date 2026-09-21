FROM node:26.9.0-alpine3.24@sha256:dbaa92e5758cbbcf85d65d5403fdb530fe3442cbe8c6dbfb7ef23365450d5070 AS build
WORKDIR /app
ARG VITE_API_BASE_PATH=/api/bridge
ENV VITE_API_BASE_PATH=${VITE_API_BASE_PATH}
COPY package*.json ./
RUN npm ci --include=optional
COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

FROM nginx:1.30.4-alpine3.24@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46
ARG RELEASE_VERSION=dev
ARG SOURCE_COMMIT=unknown
LABEL org.opencontainers.image.version="${RELEASE_VERSION}" \
      org.opencontainers.image.revision="${SOURCE_COMMIT}"
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
USER 101:101
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD wget -q -O - http://127.0.0.1:8080/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
