import os
import PyPDF2
import asyncio
import threading
import re # مكتبة النصوص للترتيب الذكي
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message

# --- الإعدادات ---
API_ID = 25039908
API_HASH = "2b23aae7b7120dca6a0a5ee2cbbbdf4c"
BOT_TOKEN = "8361569086:AAGmwzD0Y2vIPnvqJ5MG7ts_R2dLV-1CjZg"

app = Client("manga_merger_pro", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_files = {}
user_states = {}

# دالة الترتيب الطبيعي (لحل مشكلة ch1, ch2, ch10)
def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]

def progress_callback(current, total, client, message):
    if total == 0: return
    percent = current * 100 / total
    if int(percent) % 30 == 0:
        bar = '█' * int(10 * current // total) + '░' * (10 - int(10 * current // total))
        try:
            client.loop.create_task(message.edit_text(f"🚀 جاري الرفع...\n|{bar}| {percent:.1f}%"))
        except: pass

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text("أهلاً بك في بوت Speed Manga! 📁\nأرسل ملفات الـ PDF وسأقوم بترتيبها تلقائياً، ثم أرسل /merge.")

# 1. استقبال الملفات وترتيبها ذكياً
@app.on_message(filters.document & filters.private)
async def handle_pdf(client, message):
    if not message.document.file_name.lower().endswith('.pdf'):
        return await message.reply_text("❌ أرسل ملف PDF فقط!")
    
    user_id = message.from_user.id
    if user_id not in user_files: user_files[user_id] = []
    
    os.makedirs("downloads", exist_ok=True)
    # حفظ الملف باسمه الأصلي
    file_path = os.path.join("downloads", f"{user_id}_{message.document.file_name}")
    
    msg = await message.reply_text(f"📥 جاري تحميل: {message.document.file_name}...")
    await message.download(file_name=file_path)
    user_files[user_id].append(file_path)
    
    # الترتيب الطبيعي (Natural Sort) بناءً على اسم الملف
    user_files[user_id].sort(key=natural_sort_key)
    
    await msg.edit_text(
        f"✅ تم استلام وترتيب: {message.document.file_name}\n\n"
        f"📊 عدد الملفات الآن: {len(user_files[user_id])}\n"
        "💡 إذا انتهيت من إرسال جميع الفصول، أرسل الآن أمر /merge للبدء."
    )

# 2. طلب الاسم (بدون final_)
@app.on_message(filters.command("merge") & filters.private)
async def merge_command(client, message):
    user_id = message.from_user.id
    if user_id not in user_files or len(user_files[user_id]) < 2:
        return await message.reply_text("❌ أرسل ملفين على الأقل أولاً!")
    
    user_states[user_id] = {"step": "get_name"}
    await message.reply_text("📝 أرسل الآن الاسم الذي تريده للملف النهائي (سيتم استخدامه كما هو):")

# 3. معالجة الاسم والوصف والدمج
@app.on_message(filters.text & filters.private & ~filters.command("start") & ~filters.command("merge"))
async def handle_logic(client, message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    if not state: return

    if state["step"] == "get_name":
        name = message.text.strip()
        user_states[user_id]["name"] = name if name.endswith(".pdf") else name + ".pdf"
        user_states[user_id]["step"] = "get_caption"
        await message.reply_text("🖋️ تمام، أرسل الآن الوصف (Caption) الذي سيظهر تحت الملف:")

    elif state["step"] == "get_caption":
        caption = message.text.strip()
        filename = user_states[user_id]["name"]
        status_msg = await message.reply_text("⏳ جاري دمج الفصول بالترتيب الصحيح...")
        
        try:
            merger = PyPDF2.PdfMerger()
            for pdf in user_files[user_id]:
                merger.append(pdf)
            
            # تم التأكد من عدم إضافة final_
            output_path = os.path.join("downloads", f"final_{user_id}_{filename}") 
            # ملاحظة: اسم الملف البرمجي داخلي فقط، للمستخدم سيظهر باسمه المختار
            merger.write(output_path)
            merger.close()

            await client.send_document(
                chat_id=message.chat.id,
                document=output_path,
                caption=caption,
                file_name=filename, # هنا الاسم يظهر للمستخدم كما كتبه بالضبط
                progress=progress_callback,
                progress_args=(client, status_msg)
            )

            # تنظيف الملفات
            for f in user_files[user_id] + [output_path]:
                if os.path.exists(f): os.remove(f)
            user_files.pop(user_id, None)
            user_states.pop(user_id, None)
            await status_msg.delete()

        except Exception as e:
            await message.reply_text(f"❌ حدث خطأ: {str(e)}")

# --- Flask & Run ---
web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Speed Manga Bot is Running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    app.run()
