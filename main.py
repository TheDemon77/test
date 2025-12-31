import os
import PyPDF2
import asyncio
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait

# --- الإعدادات ---
API_ID = 25039908
API_HASH = "2b23aae7b7120dca6a0a5ee2cbbbdf4c"
BOT_TOKEN = "8531856638:AAF5HE6Qn0smuJDVwHMH4MPYsSU5XXWr9Gw"

app = Client("manga_merger_pro", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# مخازن البيانات
user_files = {}  # {user_id: [paths]}
user_states = {} # {user_id: {"step": "...", "name": "..."}}
status_messages = {} # لتحديث رسالة واحدة فقط للمستخدم

def progress_callback(current, total, client, message):
    if total == 0: return
    percent = current * 100 / total
    if int(percent) % 30 == 0:
        try:
            client.loop.create_task(message.edit_text(f"🚀 جاري رفع الملف المدمج...\n📊 التقدم: {percent:.1f}%"))
        except: pass

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text(
        "أهلاً بك في بوت Speed Manga! 📁\n\n"
        "💡 أرسل ملفات الـ PDF (يمكنك إرسالها دفعة واحدة).\n"
        "✅ البوت يدعم التحميل المتوازي والترتيب التلقائي.\n"
        "🔘 بعد الانتهاء، أرسل أمر /merge للبدء."
    )

# 1. التحميل المتوازي ومعالجة الملفات
@app.on_message(filters.document & filters.private)
async def handle_pdf(client, message):
    if not message.document.file_name.lower().endswith('.pdf'):
        return
    
    user_id = message.from_user.id
    if user_id not in user_files: user_files[user_id] = []
    
    # التحميل المتوازي: Pyrogram يفتح Task لكل رسالة تلقائياً
    os.makedirs("downloads", exist_ok=True)
    file_path = os.path.join("downloads", f"{user_id}_{message.document.file_name}")
    
    # تحميل الملف
    await message.download(file_name=file_path)
    if file_path not in user_files[user_id]:
        user_files[user_id].append(file_path)
    
    # تحديث رسالة حالة واحدة بدل تكرار الرسائل
    count = len(user_files[user_id])
    text = f"✅ تم استلام {count} ملفات بنجاح.\n\n📂 آخر ملف: {message.document.file_name}\n💡 إذا انتهيت، أرسل الآن أمر /merge للبدء."
    
    if user_id in status_messages:
        try:
            await status_messages[user_id].edit_text(text)
        except:
            status_messages[user_id] = await message.reply_text(text)
    else:
        status_messages[user_id] = await message.reply_text(text)

# 2. أمر الدمج وبداية طلب البيانات
@app.on_message(filters.command("merge") & filters.private)
async def merge_command(client, message):
    user_id = message.from_user.id
    if user_id not in user_files or len(user_files[user_id]) < 2:
        return await message.reply_text("❌ أرسل ملفين على الأقل أولاً!")
    
    # مسح رسالة الحالة القديمة
    if user_id in status_messages:
        del status_messages[user_id]

    user_states[user_id] = {"step": "get_name"}
    await message.reply_text("📝 ممتاز، أرسل الآن الاسم الذي تريده للملف (بدون كلمة final وبدون .pdf):")

# 3. معالجة الاسم والوصف والدمج النهائي
@app.on_message(filters.text & filters.private & ~filters.command("start"))
async def handle_logic(client, message):
    user_id = message.from_user.id
    state = user_states.get(user_id)

    if not state: return

    if state["step"] == "get_name":
        user_states[user_id]["name"] = message.text.strip() + ".pdf"
        user_states[user_id]["step"] = "get_caption"
        await message.reply_text("🖋️ أرسل الآن الوصف (Caption) الذي تريد وضعه على الملف:")

    elif state["step"] == "get_caption":
        caption = message.text.strip()
        filename = user_states[user_id]["name"]
        
        prog_msg = await message.reply_text("⏳ جاري ترتيب ودمج الملفات، انتظر قليلاً...")
        
        try:
            # الترتيب الأبجدي الصحيح بناءً على اسم الملف
            user_files[user_id].sort() 
            
            merger = PyPDF2.PdfMerger()
            for pdf in user_files[user_id]:
                merger.append(pdf)
            
            # حفظ الملف بالاسم المطلوب مباشرة (بدون زوائد)
            output_path = os.path.join("downloads", f"final_{user_id}_{filename}") # الـ final هنا للمسار فقط وليس للاسم المرسل
            merger.write(output_path)
            merger.close()

            # إرسال الملف النهائي
            await client.send_document(
                chat_id=message.chat.id,
                document=output_path,
                caption=caption,
                file_name=filename, # الاسم النظيف هنا
                progress=progress_callback,
                progress_args=(client, prog_msg)
            )

            # تنظيف كل شيء
            for f in user_files[user_id] + [output_path]:
                if os.path.exists(f): os.remove(f)
            
            user_files.pop(user_id, None)
            user_states.pop(user_id, None)
            await prog_msg.delete()
            await message.reply_text("✨ تم الانتهاء من العمل بنجاح!")

        except Exception as e:
            await message.reply_text(f"❌ حدث خطأ أثناء الدمج: {str(e)}")

# --- تشغيل ويب لـ Railway ---
web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Manga Parallel Bot is Running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    app.run()
