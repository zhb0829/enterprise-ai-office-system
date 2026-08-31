# ---- 构建阶段 ----
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

# ---- 运行阶段 ----
# dist 内容物理放置在 /admin/ 子目录下（vite base=/admin/），
# 用纯 root 方式托管，规避 alias + try_files 的回退问题。
FROM nginx:alpine
COPY --from=build /app/dist/ /usr/share/nginx/html/admin/
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
