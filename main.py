import os
import PyPDF2
import asyncio
import threading
import re
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message

# --- الإعدادات (تأكد من صحة البيانات الخاصة بك) ---
API_ID = 25039908
API_HASH = "2b23aae7b7120dca6a0a5ee2cbbbdf4c"
BOT_TOKEN = "8361569086:AAGvuIAZ7BgHyU0jbMEzC-30RB591_VV7aE"

app = Client("manga_merger_pro", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# مخازن البيانات المؤقتة
user_files = {}
user_states = {}

# 1. دالة الترتيب الذكي (الحل النهائي لمشكلة الترتيب)
def natural_sort_key(s):
    # نقوم بتوحيد شكل الاسم (تبديل _ بـ -) لدمج المجموعات المختلفة في الترتيب
    normalized_name = s.replace('_', '-')
    # تقسيم النص إلى قطع (نصوص وأرقام) لتحويل الأرقام إلى قيم حسابية
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', normalized_name)]

# دالة تحديث شريط التحميل/الرفع
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
    await message.reply_text(
        "أهلاً بك في بوت Speed Manga! 📁\n\n"
        "1️⃣ أرسل ملفات الـ PDF (سأقوم بترتيبها تلقائياً).\n"
        "2️⃣ عند الانتهاء، أرسل أمر /merge للبدء."
    )

# 1. تحديث دالة استقبال الملفات لتعديل رسالة واحدة فقط
@app.on_message(filters.document & filters.private)
async def handle_pdf(client, message):
    if not message.document.file_name.lower().endswith('.pdf'):
        return await message.reply_text("❌ أرسل ملف PDF فقط!")
    
    user_id = message.from_user.id
    if user_id not in user_files: user_files[user_id] = []
    
    os.makedirs("downloads", exist_ok=True)
    file_path = os.path.join("downloads", f"{user_id}_{message.document.file_name}")
    
    # تحميل الملف في الخلفية بدون إرسال رسالة "جاري التحميل" لكل ملف
    await message.download(file_name=file_path)
    user_files[user_id].append(file_path)
    user_files[user_id].sort(key=natural_sort_key)
    
    count = len(user_files[user_id])
    status_text = f"📊 تم استلام {count} ملفات حتى الآن...\n\n💡 أرسل /merge عندما تنتهي."

    # البحث عن رسالة الحالة السابقة وتحديثها
    if user_id not in user_states: user_states[user_id] = {}
    
    msg_id = user_states[user_id].get("status_msg_id")

    if msg_id:
        try:
            # تعديل الرسالة الموجودة بدلاً من إرسال واحدة جديدة
            await client.edit_message_text(message.chat.id, msg_id, status_text)
        except:
            # إذا حُذفت الرسالة لأي سبب، نرسل واحدة جديدة ونحفظ رقمها
            new_msg = await message.reply_text(status_text)
            user_states[user_id]["status_msg_id"] = new_msg.id
    else:
        # أول ملف يتم رفعه يرسل رسالة الحالة لأول مرة
        new_msg = await message.reply_text(status_text)
        user_states[user_id]["status_msg_id"] = new_msg.id

# 2. تحديث أمر الدمج لحذف رسالة الحالة عند البدء
@app.on_message(filters.command("merge") & filters.private)
async def merge_command(client, message):
    user_id = message.from_user.id
    if user_id not in user_files or len(user_files[user_id]) < 2:
        return await message.reply_text("❌ أرسل ملفين على الأقل أولاً!")
    
    # حذف رسالة التنبيه المزعجة لتنظيف الشات قبل عرض الترتيب
    msg_id = user_states.get(user_id, {}).get("status_msg_id")
    if msg_id:
        try: await client.delete_messages(message.chat.id, msg_id)
        except: pass

    # عرض الترتيب كما طلبته سابقاً
    files_list = "\n".join([os.path.basename(f).split('_', 1)[1] for f in user_files[user_id]])
    await message.reply_text(f"🔍 الترتيب الذي سيتم الدمج به:\n\n{files_list}")
    
    user_states[user_id]["step"] = "get_name"
    await message.reply_text("📝 أرسل الآن الاسم الذي تريده للملف النهائي:")
    
# 4. معالجة النصوص (الاسم ثم الوصف ثم التنفيذ)
@app.on_message(filters.text & filters.private & ~filters.command(["start", "merge"]))
async def handle_logic(client, message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    if not state: return

    # الخطوة الأولى: استلام الاسم
    if state["step"] == "get_name":
        user_states[user_id]["name"] = message.text.strip()
        user_states[user_id]["step"] = "get_caption"
        await message.reply_text("🖋️ تمام، أرسل الآن الوصف (Caption) الذي سيظهر تحت الملف:")

    # الخطوة الثانية: استلام الوصف والدمج
    elif state["step"] == "get_caption":
        caption = message.text.strip()
        filename = user_states[user_id]["name"]
        if not filename.lower().endswith(".pdf"): filename += ".pdf"
        
        status_msg = await message.reply_text("⏳ جاري دمج الملفات بالترتيب الصحيح... انتظر قليلاً.")
        
        try:
            merger = PyPDF2.PdfMerger()
            for pdf in user_files[user_id]:
                merger.append(pdf)
            
            # مسار مؤقت للملف المدمج
            output_path = os.path.join("downloads", f"temp_{user_id}.pdf")
            merger.write(output_path)
            merger.close()

            # إرسال الملف النهائي بالاسم والوصف المختارين
            await client.send_document(
                chat_id=message.chat.id,
                document=output_path,
                caption=caption,
                file_name=filename, # الاسم الذي كتبه المستخدم مباشرة
                progress=progress_callback,
                progress_args=(client, status_msg)
            )
            
            await message.reply_text("✅ تم الانتهاء من التنزيل والدمج والرفع بنجاح!")

            # تنظيف المجلد وحذف الملفات المؤقتة
            for f in user_files[user_id] + [output_path]:
                if os.path.exists(f): os.remove(f)
            user_files.pop(user_id, None)
            user_states.pop(user_id, None)
            await status_msg.delete()

        except Exception as e:
            await message.reply_text(f"❌ حدث خطأ غير متوقع: {str(e)}")

# --- تشغيل سيرفر Flask لـ Railway ---
web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Speed Manga Bot is Active!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    app.run()
