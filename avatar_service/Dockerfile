FROM python:3.11-slim
WORKDIR /app
COPY avatar_service/requirements.txt ./avatar_service/requirements.txt
RUN pip install --no-cache-dir -r avatar_service/requirements.txt
COPY avatar_service ./avatar_service
ENV PORT=8800 ASSET_DIR=/app/avatar_service/assets
EXPOSE 8800
CMD ["sh", "-c", "uvicorn avatar_service.app:get_app --factory --host 0.0.0.0 --port ${PORT}"]
