import os
import re
import shutil
import asyncio
from pyrogram import Client, filters
from PyPDF2 import PdfMerger
from flask import Flask
from threading import Thread

# --- بيانات البوت ---
API_ID = 25039908  
API_HASH = "2b23aae7b7120dca6a0a5ee2cbbbdf4c"
BOT_TOKEN = "8544321667:AAERohdWfuUDonBm5hat_7BnJFMuUlFJcNI"

app = Client("smart_manga_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# الذاكرة المؤقتة
users_db = {}

# --- 🧠 دالة الترتيب الذكي (الجوهرية) ---
def smart_sort_key(file_path):
    """
    تستخرج الأرقام من اسم الملف وترتب بناء عليها.
    مثال: 'black-clover_ch217.pdf' -> سيتم استخراج الرقم 217 للترتيب.
    """
    base_name = os.path.basename(file_path)
    # البحث عن كل الأرقام في الاسم
    numbers = re.findall(r'\d+', base_name)
    if numbers:
        # تحويل الأرقام لنصوص صحيحة (مثلاً 217 أهم من الاسم نفسه)
        # نقوم بإرجاع قائمة أرقام، ثم الاسم للنصوص المتشابهة
        return [int(num) for num in numbers]
    else:
        # لو مفيش أرقام خالص، رتب أبجدي عادي
        return base_name.lower()

# --- محرك الدمج ---
def merge_engine(files, output_path):
    merger = PdfMerger()
    try:
        # الترتيب هنا قبل الدمج مباشرة
        files.sort(key=smart_sort_key)
        
        for file in files:
            merger.append(file)
        merger.write(output_path)
        merger.close()
        return True
    except Exception as e:
        print(f"Merge Error: {e}")
        return False

# --- 1. الأمر: /start (تنظيف وبدء جديد) ---
@app.on_message(filters.command(["start", "clear"]))
async def start_handler(client, message):
    uid = message.from_user.id
    # تنظيف ملفات المستخدم القديمة فوراً
    if uid in users_db:
        shutil.rmtree(f"downloads/{uid}", ignore_errors=True)
    
    users_db[uid] = {'files': [], 'step': 'collecting'}
    
    await message.reply_text(
        "🧹 **تم تنظيف الذاكرة!**\n\n"
        "1️⃣ وجه (Forward) الملفات الآن (من 1 لـ 20 مثلاً).\n"
        "2️⃣ **لن أرسل أي رد** أثناء التحميل لتوفير الوقت.\n"
        "3️⃣ عندما تنتهي، أرسل: **/done**"
    )

# --- 2. الاستلام الصامت (The Silent Receiver) ---
@app.on_message(filters.document)
async def document_handler(client, message):
    if not message.document.file_name.lower().endswith('.pdf'): return

    uid = message.from_user.id
    if uid not in users_db: users_db[uid] = {'files': [], 'step': 'collecting'}
    
    # لو المستخدم في مرحلة انتظار الاسم، نتجاهل الملفات الجديدة منعاً للأخطاء
    if users_db[uid].get('step') != 'collecting':
        return

    # التحميل فوراً
    user_dir = f"downloads/{uid}"
    os.makedirs(user_dir, exist_ok=True)
    file_path = os.path.join(user_dir, message.document.file_name)
    
    # تحميل صامت (بدون await status msg)
    await message.download(file_name=file_path)
    users_db[uid]['files'].append(file_path)
    print(f"User {uid}: Downloaded {message.document.file_name}") 

# --- 3. الأمر: /done (إنهاء التجميع) ---
@app.on_message(filters.command("done"))
async def done_handler(client, message):
    uid = message.from_user.id
    if uid not in users_db or not users_db[uid]['files']:
        return await message.reply_text("❌ لم ترسل لي أي ملفات بعد!")
    
    files_count = len(users_db[uid]['files'])
    users_db[uid]['step'] = 'waiting_name'
    
    await message.reply_text(
        f"✅ **تم استلام {files_count} ملف بنجاح!**\n"
        f"🔄 سيتم الترتيب تلقائياً حسب أرقام الفصول.\n\n"
        f"📝 **أرسل الآن اسم الملف النهائي:**"
    )

# --- 4. استلام الاسم والدمج ---
@app.on_message(filters.text & ~filters.command(["start", "done", "clear"]))
async def name_and_process(client, message):
    uid = message.from_user.id
    data = users_db.get(uid)
    
    if not data or data['step'] != 'waiting_name':
        return

    # استلام الاسم
    filename = message.text.strip().replace('/', '-')
    if not filename.endswith('.pdf'): filename += ".pdf"
    
    msg = await message.reply_text("⏳ **جاري الترتيب والدمج...**")
    
    data['step'] = 'processing' # قفل الاستلام
    output_path = f"downloads/{uid}/{filename}"
    
    # تشغيل الدمج
    loop = asyncio.get_event_loop()
    success = await loop.run_in_executor(None, merge_engine, data['files'], output_path)
    
    if success:
        await msg.edit_text("📤 **جاري الرفع...**")
        try:
            await client.send_document(
                chat_id=message.chat.id,
                document=output_path,
                caption=f"📦 **{filename}**\n📄 عدد الفصول: {len(data['files'])}"
            )
            await msg.delete()
            # تنظيف بعد النجاح مباشرة عشان تكون جاهز للدفعة القادمة
            shutil.rmtree(f"downloads/{uid}", ignore_errors=True)
            users_db[uid] = {'files': [], 'step': 'collecting'}
            await message.reply_text("✅ **تم! أرسل الدفعة التالية (مثلاً 21-40) وقم بتوجيهها مباشرة.**")
            
        except Exception as e:
            await msg.edit_text(f"❌ خطأ في الرفع: {e}")
    else:
        await msg.edit_text("❌ حدث خطأ في ملفات PDF، تأكد أنها سليمة.")

# تشغيل السيرفر (Railway Support)
web = Flask(__name__)
@web.route('/')
def home(): return "Bot OK"

def run_web():
    web.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    app.run()
