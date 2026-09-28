FROM node:24.18.0-alpine3.24@sha256:a0b9bf06e4e6193cf7a0f58816cc935ff8c2a908f81e6f1a95432d679c54fbfd AS build
WORKDIR /app
ARG VITE_API_BASE_PATH=/api/bridge
ENV VITE_API_BASE_PATH=${VITE_API_BASE_PATH}
COPY package*.json ./
RUN npm ci --include=optional
COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

FROM nginx:1.30.4-alpine3.24@sha256:dc5069ad14f19660b141b21236140b91656bf89bbc3e2417c70ae650cd66104c
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
