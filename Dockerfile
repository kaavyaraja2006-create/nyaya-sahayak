# UNTESTED in the build environment (no Docker there). The server itself has no npm dependencies.
FROM node:22-slim
WORKDIR /app
COPY dist ./dist
COPY backend/package.json ./backend/package.json
COPY backend/src ./backend/src
COPY backend/mcp-server.js ./backend/mcp-server.js
ENV NODE_ENV=production HOST=0.0.0.0 PORT=8000 DATA_DIR=/data
RUN mkdir /data && chown node:node /data
VOLUME /data
USER node
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD node -e "fetch('http://127.0.0.1:8000/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "--disable-warning=ExperimentalWarning", "backend/src/server.js"]
