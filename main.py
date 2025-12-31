import os
import PyPDF2
import asyncio
import threading
import re
from flask import Flask
from pyrogram import Client, filters

# --- الإعدادات ---
API_ID = 25039908
API_HASH = "2b23aae7b7120dca6a0a5ee2cbbbdf4c"
BOT_TOKEN = "8361569086:AAF2rkOHMeIpYlj4890LRinOToPKrNWAokw"

app = Client("manga_merger_pro", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_files = {}
user_states = {}

# 1. دالة الترتيب الذكي (تتعرف على الأرقام داخل النصوص وترتبها حسابياً)
def natural_sort_key(s):
    # تبحث عن الأرقام وتحولها لـ int للمقارنة الصحيحة
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]

@app.on_message(filters.command("start") & filters.private)
async def start(client, message):
    await message.reply_text("أهلاً بك في Speed Manga! 📁\nأرسل ملفات الـ PDF وسأرتبها لك ترتيباً صحيحاً (1, 2, 10, 20...).")

# 2. استقبال الملفات وحفظها
@app.on_message(filters.document & filters.private)
async def handle_pdf(client, message):
    if not message.document.file_name.lower().endswith('.pdf'):
        return await message.reply_text("❌ أرسل ملف PDF فقط!")
    
    user_id = message.from_user.id
    if user_id not in user_files: user_files[user_id] = []
    
    os.makedirs("downloads", exist_ok=True)
    # نحفظ الملف باسمه الأصلي في مجلد التحميلات
    file_path = os.path.join("downloads", f"{user_id}_{message.document.file_name}")
    
    msg = await message.reply_text(f"📥 جاري تحميل: {message.document.file_name}...")
    await message.download(file_name=file_path)
    user_files[user_id].append(file_path)
    
    # أهم خطوة: الترتيب باستخدام الدالة الذكية بعد كل إضافة
    user_files[user_id].sort(key=natural_sort_key)
    
    await msg.edit_text(
        f"✅ تم استلام: {message.document.file_name}\n"
        f"📊 عدد الملفات الآن: {len(user_files[user_id])}\n\n"
        "💡 إذا انتهيت، أرسل أمر /merge للبدء."
    )

# 3. أمر الدمج وطلب الاسم والوصف
@app.on_message(filters.command("merge") & filters.private)
async def merge_command(client, message):
    user_id = message.from_user.id
    if user_id not in user_files or len(user_files[user_id]) < 2:
        return await message.reply_text("❌ أرسل ملفين على الأقل أولاً!")
    
    # عرض قائمة الملفات المرتبة للتأكيد (اختياري لكن مفيد)
    files_list = "\n".join([os.path.basename(f).split('_', 1)[1] for f in user_files[user_id]])
    await message.reply_text(f"📝 الترتيب الحالي للملفات:\n{files_list}")
    
    user_states[user_id] = {"step": "get_name"}
    await message.reply_text("أرسل الآن الاسم الذي تريده للملف النهائي (بدون أي إضافات):")

@app.on_message(filters.text & filters.private & ~filters.command(["start", "merge"]))
async def handle_logic(client, message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    if not state: return

    if state["step"] == "get_name":
        user_states[user_id]["name"] = message.text.strip()
        user_states[user_id]["step"] = "get_caption"
        await message.reply_text("🖋️ تمام، أرسل الآن الوصف (Caption) الذي تريده:")

    elif state["step"] == "get_caption":
        caption = message.text.strip()
        filename = user_states[user_id]["name"]
        if not filename.lower().endswith(".pdf"): filename += ".pdf"
        
        status_msg = await message.reply_text("⏳ جاري دمج الملفات بالترتيب الذكي...")
        
        try:
            merger = PyPDF2.PdfMerger()
            for pdf in user_files[user_id]:
                merger.append(pdf)
            
            # اسم الملف الداخلي لا يهم، المهم الاسم الذي سيظهر للمستخدم (file_name)
            output_path = os.path.join("downloads", f"result_{user_id}.pdf")
            merger.write(output_path)
            merger.close()

            await client.send_document(
                chat_id=message.chat.id,
                document=output_path,
                caption=caption,
                file_name=filename # هنا نضع الاسم الذي اختاره المستخدم مباشرة
            )
            
            await message.reply_text("✅ تم الانتهاء! إذا أردت دمج ملفات أخرى، ابدأ بإرسالها الآن.")

            # تنظيف الذاكرة والملفات
            for f in user_files[user_id] + [output_path]:
                if os.path.exists(f): os.remove(f)
            user_files.pop(user_id, None)
            user_states.pop(user_id, None)
            await status_msg.delete()

        except Exception as e:
            await message.reply_text(f"❌ حدث خطأ أثناء الدمج: {str(e)}")

# --- تشغيل البوت ---
if __name__ == "__main__":
    app.run()
