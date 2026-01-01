# استخدام نسخة بايثون رسمية وخفيفة
FROM python:3.10-slim

# تحديث النظام وتثبيت Ghostscript وأدوات git (مهمة لبعض المكتبات)
RUN apt-get update && \
    apt-get install -y ghostscript git && \
    rm -rf /var/lib/apt/lists/*

# إعداد مجلد العمل
WORKDIR /app

# نسخ ملف المتطلبات أولاً لتسريع البناء
COPY requirements.txt .

# تثبيت مكتبات بايثون
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات البوت
COPY . .

# أمر تشغيل البوت (تأكد أن اسم ملفك هو main.py)
CMD ["python", "main.py"]
