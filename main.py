import os
import shutil
import asyncio
from pyrogram import Client, filters
from PyPDF2 import PdfMerger
from flask import Flask
from threading import Thread

# --- إعدادات البوت ---
API_ID = 25039908  
API_HASH = "2b23aae7b7120dca6a0a5ee2cbbbdf4c"
BOT_TOKEN = "8198010213:AAFQXf43_4tei9ijTs-zOCB5iVvYa9N8b_0"

# إضافة in_memory=True حل لمشكلة الـ FloodWait والتوكن
app = Client(
    "simple_merger",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True, 
    workers=4
)

# قاعدة البيانات والأقفال
users_data = {}
user_locks = {} # هذا هو الحل الجذري للتكرار

def get_lock(uid):
    if uid not in user_locks:
        user_locks[uid] = asyncio.Lock()
    return user_locks[uid]

# --- دالة مساعدة لترتيب الملفات (عشان 10 تيجي بعد 9) ---
import re
def sort_key(s):
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', os.path.basename(s))]

# --- 1. الأمر Start (تنظيف شامل) ---
@app.on_message(filters.command(["start", "reset"]))
async def start(client, message):
    uid = message.from_user.id
    if uid in users_data:
        path = f"downloads/{uid}"
        if os.path.exists(path): shutil.rmtree(path, ignore_errors=True)
        del users_data[uid]
    
    await message.reply_text(
        "👋 **نظام الدمج البسيط**\n\n"
        "1. وجه (Forward) الملفات.\n"
        "2. اكتب /done لما تخلص.\n\n"
        "لن أرد عليك مع كل ملف لتسريع العمل."
    )

# --- 2. استلام الملفات (تحميل صامت) ---
@app.on_message(filters.document)
async def handle_doc(client, message):
    if not message.document.file_name.lower().endswith('.pdf'): return
    
    uid = message.from_user.id
    lock = get_lock(uid)

    # استخدام القفل لضمان عدم تداخل العمليات
    async with lock:
        if uid not in users_data:
            users_data[uid] = {'files': [], 'state': 'collecting'}
            os.makedirs(f"downloads/{uid}", exist_ok=True)
        
        # لو المستخدم مش في حالة تجميع، نرفض الملف
        if users_data[uid]['state'] != 'collecting':
            return

        # التحميل
        try:
            f_path = f"downloads/{uid}/{message.document.file_name}"
            await message.download(file_name=f_path)
            users_data[uid]['files'].append(f_path)
            # مفيش أي رد هنا (Silent)
        except Exception as e:
            print(f"Error dl: {e}")

# --- 3. أمر Done (مع منع التكرار الصارم) ---
@app.on_message(filters.command("done"))
async def done(client, message):
    uid = message.from_user.id
    if uid not in users_data: return await message.reply_text("❌ ابدأ بـ /start")

    lock = get_lock(uid)
    async with lock:
        # فحص الحالة: لو احنا مش في "تجميع" يبقي الأمر ده اتنفذ قبل كده
        # وهذا يمنع الرد المزدوج 100%
        if users_data[uid]['state'] != 'collecting':
            return 
            
        users_data[uid]['state'] = 'waiting_name'
        count = len(users_data[uid]['files'])
        
        await message.reply_text(
            f"✅ تم استلام {count} ملف.\n"
            f"✍️ **ارسل اسم الملف النهائي:**"
        )

# --- 4. الدمج والرفع (Robust) ---
@app.on_message(filters.text & ~filters.command(["start", "done"]))
async def process(client, message):
    uid = message.from_user.id
    if uid not in users_data: return
    
    lock = get_lock(uid)
    async with lock:
        # فحص الحالة تاتي لمنع التكرار
        if users_data[uid]['state'] != 'waiting_name':
            return
            
        name = message.text.strip().replace('/', '-')
        if not name.endswith('.pdf'): name += ".pdf"
        
        users_data[uid]['state'] = 'processing'
        msg = await message.reply_text("⏳ جاري الدمج...")

        out_path = f"downloads/{uid}/{name}"
        files = sorted(users_data[uid]['files'], key=sort_key)
        
        if not files:
            await msg.edit_text("❌ لا توجد ملفات!")
            users_data[uid]['state'] = 'collecting'
            return

        # عملية الدمج المباشرة (بدون تعقيدات)
        try:
            merger = PdfMerger()
            for pdf in files:
                merger.append(pdf)
            
            merger.write(out_path)
            merger.close()
            
        except Exception as e:
            await msg.edit_text(f"❌ خطأ تقني في الدمج: {e}")
            return

        # الرفع
        await msg.edit_text("🚀 جاري الرفع...")
        try:
            await client.send_document(
                message.chat.id,
                document=out_path,
                caption=f"📦 {name}"
            )
            await msg.delete()
            await message.reply_text("✅ تم.")
            
            # تنظيف
            shutil.rmtree(f"downloads/{uid}", ignore_errors=True)
            del users_data[uid]
            
        except Exception as e:
            await msg.edit_text(f"❌ خطأ في الرفع: {e}")

# تشغيل
app_web = Flask(__name__)
@app_web.route('/')
def h(): return "Bot Running"
def r(): app_web.run(host='0.0.0.0', port=8080)

if __name__ == "__main__":
    Thread(target=r, daemon=True).start()
    print("Bot started...")
    app.run()
