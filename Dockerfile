# 1. Sử dụng Python chính thức (bản slim để nhẹ hơn)
FROM python:3.10-slim

# 2. Thiết lập thư mục làm việc trong container
WORKDIR /app

# 3. Cài đặt các gói hệ thống cần thiết (nếu cần)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 4. Copy file danh sách thư viện
COPY requirements.txt .

# 5. Cài đặt thư viện (bao gồm ortools, fastapi, uvicorn)
RUN pip install --no-cache-dir -r requirement.txt

# 6. Copy toàn bộ code vào thư mục /app
COPY . .

# 7. Mở cổng 8000 cho FastAPI
EXPOSE 8000

# 8. Lệnh chạy server
# Lưu ý: Thay 'main:app' nếu file chạy của bạn tên là server.py hoặc app.py
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
