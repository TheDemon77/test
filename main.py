import os, PyPDF2, asyncio, threading, re, time
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait

# --- الإعدادات ---
API_ID = 25039908
API_HASH = "2b23aae7b7120dca6a0a5ee2cbbbdf4c"
BOT_TOKEN = "8531856638:AAGXqTihxLHaJlNJGXk8PJjiKawzg8KOtjw"

app = Client("manga_merger_pro", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# مخازن البيانات
user_files = {}
user_states = {}
# تحديد أقصى عدد تحميلات متزامنة لتجنب الكراش (Railway محدود الموارد)
download_semaphore = asyncio.Semaphore(5) 

def natural_sort_key(s):
    normalized_name = s.replace('_', '-')
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', normalized_name)]

# دالة شريط التقدم العامة (للتحميل والرفع)
async def progress_bar(current, total, status_msg, action_type="تحميل"):
    try:
        if total == 0: return
        percent = current * 100 / total
        bar_length = 10
        filled = int(bar_length * current // total)
        bar = '█' * filled + '░' * (bar_length - filled)
        
        # التحديث فقط عند تغير الرقم الصحيح للنسبة لتقليل الضغط
        text = f"⚙️ **جاري {action_type}...**\n|{bar}| {percent:.1f}%"
        await status_msg.edit_text(text)
    except: pass

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text("🚀 **بوت دمج المانجا العملاق جاهز!**\n\n- أرسل أي عدد من الملفات (حتى 100+).\n- سأقوم بتحميلهم وترتيبهم.\n- عند الانتهاء أرسل /merge للتقسيم والدمج.")

# --- 1. استقبال وتحميل الملفات بشاشة حالة ---
@app.on_message(filters.document & filters.private)
async def handle_pdf(client, message):
    if not message.document.file_name.lower().endswith('.pdf'): return
    
    user_id = message.from_user.id
    if user_id not in user_files: user_files[user_id] = []
    
    status_msg = await message.reply_text(f"⏳ جاري تجهيز تحميل: {message.document.file_name}")
    
    async with download_semaphore: # التحكم في التزامن لمنع الكراش
        os.makedirs(f"downloads/{user_id}", exist_ok=True)
        file_path = os.path.join(f"downloads/{user_id}", message.document.file_name)
        
        try:
            await message.download(
                file_name=file_path,
                progress=progress_bar,
                progress_args=(status_msg, "تحميل")
            )
            user_files[user_id].append(file_path)
            await status_msg.edit_text(f"✅ تم تحميل: {message.document.file_name}\n📊 الإجمالي: {len(user_files[user_id])} ملف.")
            await asyncio.sleep(1) # تأخير بسيط لراحة السيرفر
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit_text(f"❌ فشل تحميل {message.document.file_name}: {str(e)}")

# --- 2. أمر الدمج وطلب التقسيم ---
@app.on_message(filters.command("merge") & filters.private)
async def merge_req(client, message):
    user_id = message.from_user.id
    if user_id not in user_files or len(user_files[user_id]) < 2:
        return await message.reply_text("❌ أرسل ملفين على الأقل!")
    
    user_files[user_id].sort(key=natural_sort_key) # الترتيب الطبيعي
    
    user_states[user_id] = {"step": "get_split_size"}
    await message.reply_text(
        f"📋 تم ترتيب {len(user_files[user_id])} ملفاً.\n\n"
        "🔢 **تريد دمج كل كم فصل في ملف واحد؟**\n"
        "(أرسل رقم فقط، مثلاً: 20)"
    )

# --- 3. معالجة المنطق (التقسيم والدمج والرفع) ---
@app.on_message(filters.text & filters.private & ~filters.command(["start", "merge"]))
async def logic(client, message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    if not state: return

    if state["step"] == "get_split_size":
        if not message.text.isdigit():
            return await message.reply_text("❌ يرجى إرسال رقم صحيح!")
        
        split_size = int(message.text)
        user_states[user_id]["split_size"] = split_size
        user_states[user_id]["step"] = "get_main_name"
        await message.reply_text("📝 أرسل الآن الاسم الأساسي للملفات (مثال: ملوك المانجا):")

    elif state["step"] == "get_main_name":
        main_name = message.text.strip()
        split_size = user_states[user_id]["split_size"]
        files = user_files[user_id]
        
        # تقسيم الملفات إلى مجموعات (Chunks)
        chunks = [files[i:i + split_size] for i in range(0, len(files), split_size)]
        
        await message.reply_text(f"📦 سيتم إنتاج {len(chunks)} ملفات مدمجة...")

        for index, chunk in enumerate(chunks, 1):
            status_msg = await message.reply_text(f"🔄 جاري معالجة المجموعة {index}...")
            try:
                merger = PyPDF2.PdfMerger()
                for pdf in chunk:
                    merger.append(pdf)
                
                output_name = f"{main_name} - الجزء {index}.pdf"
                output_path = f"downloads/{user_id}/final_{index}.pdf"
                merger.write(output_path)
                merger.close()

                # الرفع مع شاشة حالة
                await client.send_document(
                    chat_id=message.chat.id,
                    document=output_path,
                    caption=f"✅ {output_name}\n📚 يحتوي على {len(chunk)} فصل.",
                    file_name=output_name,
                    progress=progress_bar,
                    progress_args=(status_msg, f"رفع الجزء {index}")
                )
                os.remove(output_path)
                await status_msg.delete()
            except Exception as e:
                await message.reply_text(f"❌ خطأ في المجموعة {index}: {str(e)}")

        # تنظيف كل الملفات بعد الانتهاء
        for f in files:
            if os.path.exists(f): os.remove(f)
        user_files.pop(user_id, None)
        user_states.pop(user_id, None)
        await message.reply_text("✨ تم الانتهاء من جميع المجموعات بنجاح!")

# --- Flask & Run ---
web_app = Flask(__name__)
@web_app.route('/')
def home(): return "Manga Merger Machine Active!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    app.run()
