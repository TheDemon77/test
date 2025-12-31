import os
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import ChatAdminRequired, ChannelPrivate, UserNotParticipant
import PyPDF2
import asyncio
from datetime import datetime
import zipfile
from flask import Flask
import threading

# --- إعدادات العميل (استخدام متغيرات البيئة أفضل للسكورتي في ريلوي) ---
API_ID = int(os.environ.get("API_ID", 25039908))
API_HASH = os.environ.get("API_HASH", "2b23aae7b7120dca6a0a5ee2cbbbdf4c")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8361569086:AAGQ97uNbOrBAQ0w0zWPo2XD7w6FVk8WEWs")

app = Client("pdf_merger_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# المتغيرات العامة
user_files = {}
user_states = {}
user_merges = {}
MAX_MERGES = 5  # رفعنا الحد لـ 5 بما إن السيرفر قوي
CLEANUP_DELAY = 300 

# --- إصلاح دالة التقدم (Progress) لتكون متوافقة مع Pyrogram ---
def progress_callback(current, total, client, message):
    if total == 0: return
    percent = current * 100 / total
    if int(percent) % 20 == 0:  # التحديث كل 20% لتقليل الضغط على التليجرام
        bar_length = 10
        filled = int(bar_length * current // total)
        bar = '█' * filled + '░' * (bar_length - filled)
        try:
            # تشغيل التعديل في الخلفية بدون حجز الـ Thread
            client.loop.create_task(message.edit_text(f"🚀 جاري المعالجة...\n|{bar}| {percent:.1f}%"))
        except: pass

async def cleanup_user_data(user_id: int):
    await asyncio.sleep(CLEANUP_DELAY)
    if user_id in user_files:
        for file in user_files[user_id]:
            if os.path.exists(file): os.remove(file)
        user_files[user_id] = []

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    user_id = message.from_user.id
    merges_left = MAX_MERGES - user_merges.get(user_id, 0)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("دمج الملفات بالترتيب 📑", callback_data="merge")],
        [InlineKeyboardButton("حذف المؤقت 🗑", callback_data="clear")]
    ])
    await message.reply_text(
        f"مرحباً بك في بوت Speed Manga! 📁\n\n"
        f"عدد محاولاتك: {merges_left} من {MAX_MERGES}\n"
        "أرسل ملفات الـ PDF وسأقوم بترتيبها أبجدياً ودمجها.",
        reply_markup=keyboard
    )

async def perform_merge(user_id, chat_id, filename, client):
    if not user_files.get(user_id) or len(user_files[user_id]) < 2:
        return "تحتاج لملفين على الأقل."

    # --- الحل السحري لمشكلة الترتيب ---
    user_files[user_id].sort() # سيرتب الملفات حسب اسمها (373، 374، 375...)

    status_msg = await client.send_message(chat_id, "⏳ جاري دمج وضغط الملفات...")
    
    try:
        merger = PyPDF2.PdfMerger()
        for pdf in user_files[user_id]:
            merger.append(pdf)

        if not os.path.exists("downloads"): os.makedirs("downloads")
        output_pdf = os.path.join("downloads", filename)
        merger.write(output_pdf)
        merger.close()

        zip_path = output_pdf.replace('.pdf', '.zip')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(output_pdf, arcname=filename)

        await client.send_document(
            chat_id=chat_id,
            document=zip_path,
            caption=f"✅ تم الدمج بنجاح!\n📦 الملف: {filename}\n📚 عدد الفصول: {len(user_files[user_id])}",
            progress=progress_callback,
            progress_args=(client, status_msg)
        )
        
        # تنظيف
        for f in [output_pdf, zip_path] + user_files[user_id]:
            if os.path.exists(f): os.remove(f)
        user_files[user_id] = []
        await status_msg.delete()

    except Exception as e:
        await client.send_message(chat_id, f"❌ خطأ: {str(e)}")

@app.on_callback_query()
async def handle_callback(client, callback_query):
    user_id = callback_query.from_user.id
    data = callback_query.data

    if data == "merge":
        if user_id not in user_files or len(user_files[user_id]) < 2:
            await callback_query.answer("أرسل ملفين أولاً!", show_alert=True)
        else:
            await callback_query.message.reply_text("أرسل الآن اسم الملف النهائي (مثال: ملوك_الكيمياء.pdf)")

    elif data == "clear":
        user_files[user_id] = []
        await callback_query.answer("تم مسح قائمتك.")

@app.on_message(filters.document & filters.private)
async def handle_pdf(client, message):
    if not message.document.file_name.lower().endswith('.pdf'): return
    
    user_id = message.from_user.id
    if user_id not in user_files: user_files[user_id] = []
    
    downloads_dir = "downloads"
    os.makedirs(downloads_dir, exist_ok=True)
    
    # حفظ الملف باسمه الأصلي لضمان نجاح عملية الـ .sort() لاحقاً
    file_path = os.path.join(downloads_dir, message.document.file_name)
    
    msg = await message.reply_text("📥 جاري التحميل...")
    await message.download(file_name=file_path)
    await msg.delete()
    
    user_files[user_id].append(file_path)
    await message.reply_text(f"✅ أضيف للفهرس: {message.document.file_name}\nعدد الملفات: {len(user_files[user_id])}")

@app.on_message(filters.text & filters.private & ~filters.command("start"))
async def handle_text(client, message):
    user_id = message.from_user.id
    if user_id in user_files and len(user_files[user_id]) >= 2:
        filename = message.text if message.text.endswith(".pdf") else message.text + ".pdf"
        await perform_merge(user_id, message.chat.id, filename, client)

# --- Flask Server for Railway ---
web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Manga Merger is Alive!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Bot is starting...")
    app.run()
