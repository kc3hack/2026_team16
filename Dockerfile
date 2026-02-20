FROM python:3.11-slim

WORKDIR /app

# 先にライブラリ一覧をコピーしてインストール
COPY requirements.txt .
# requirements.txtがまだ空なら、直接指定でインストールもしておく
RUN pip install --no-cache-dir -r requirements.txt || true
RUN pip install --no-cache-dir fastapi[standard] uvicorn requests
RUN apt-get update && apt-get install -y network-manager

# 全ファイルをコピー
COPY . .

# backendフォルダの中を探すように指示する
CMD ["uvicorn", "main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]