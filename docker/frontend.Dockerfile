FROM node:20-alpine AS builder

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
ARG GOOGLE_MAPS_API_KEY
RUN sed -i "s/%GOOGLE_MAPS_API_KEY%/${GOOGLE_MAPS_API_KEY}/" src/environments/environment.prod.ts
RUN npx ng build --configuration=production

FROM nginx:alpine

COPY --from=builder /app/dist/frontend/browser /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
