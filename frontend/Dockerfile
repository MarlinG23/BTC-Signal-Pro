FROM node:20-slim AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
EXPOSE 8080
# Substitute $PORT and $BACKEND_URL into nginx config at container startup.
# Single-quoting each variable name tells envsubst to only replace those two,
# leaving nginx's own $uri / $host / $scheme / etc. untouched.
CMD ["/bin/sh", "-c", "envsubst '$PORT $BACKEND_HOST $BACKEND_PORT' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && exec nginx -g 'daemon off;'"]
