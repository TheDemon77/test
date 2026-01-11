import os
import re
import shutil
import time
import asyncio
import logging
from threading import Thread
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, MessageNotModified
from PyPDF2 import PdfMerger
from flask import Flask

# ==========================================
# ⚙️ إعدادات البوت
# ==========================================
API_ID = 25039908  
API_HASH = "2b23aae7b7120dca6a0a5ee2cbbbdf4c"
BOT_TOKEN = "8544321667:AAHG5AnLLUMSE9P52TXBnMc6DH4KQl4zNnk"

# تقليل الإزعاج في الكونسول
logging.basicConfig(level=logging.ERROR)

app = Client(
    "manga_pro_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=10, 
    max_concurrent_transmissions=3
)

# ==========================================
# 🧠 إدارة الجلسات (بمنطق الحالة الصارم)
# ==========================================

class Session:
    def __init__(self, uid):
        self.uid = uid
        self.files = []
        self.total_size = 0
        self.msg = None          # رسالة لوحة التحكم
        self.last_update = 0     # وقت آخر تحديث للرسالة
        # الحالات: idle -> collecting -> waiting_name -> processing
        self.state = 'idle'      
        self.lock = asyncio.Lock() # قفل لتنظيم الملفات

sessions = {}

def get_session(uid):
    if uid not in sessions:
        sessions[uid] = Session(uid)
        # تنظيف المجلد عند بداية الجلسة
        path = f"downloads/{uid}"
        if os.path.exists(path): shutil.rmtree(path, ignore_errors=True)
        os.makedirs(path, exist_ok=True)
    return sessions[uid]

def natural_key(file_path):
    """ترتيب الملفات بذكاء: الفصل 10 بعد 9"""
    base = os.path.basename(file_path)
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', base)]

def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0: return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"

# ==========================================
# 🎮 الأوامر والمعالجة
# ==========================================

@app.on_message(filters.command(["start", "reset"]))
async def start(client, message):
    uid = message.from_user.id
    if uid in sessions:
        shutil.rmtree(f"downloads/{uid}", ignore_errors=True)
        del sessions[uid]
    
    await message.reply_text(
        "👋 **مرحباً بك في نظام الدمج الذكي**\n\n"
        "1️⃣ وجه (Forward) الملفات الآن (سأظهر لك عداد حي).\n"
        "2️⃣ عند الانتهاء أرسل **/done**.\n\n"
        "🔒 **ملاحظة:** أنا أمنع التكرار، وأرتب الفصول بدقة."
    )

# --- 1. استلام الملفات (المشكلة كانت هنا واتحلت) ---
@app.on_message(filters.document)
async def handle_docs(client, message):
    if not message.document.file_name.lower().endswith('.pdf'): return

    uid = message.from_user.id
    sess = get_session(uid)

    # لو البوت مشغول أو بيطلب اسم، يتجاهل الملفات الجديدة لمنع اللخبطة
    if sess.state not in ['idle', 'collecting']:
        return 

    sess.state = 'collecting'

    # التحميل
    try:
        f_path = f"downloads/{uid}/{message.document.file_name}"
        await message.download(file_name=f_path)
        
        async with sess.lock: # طابور نظامي
            sess.files.append(f_path)
            sess.total_size += message.document.file_size
            
            # --- منطق تحديث "لوحة التحكم" ---
            count = len(sess.files)
            size_fmt = format_size(sess.total_size)
            
            text = (
                f"📥 **جاري تجميع الملفات...**\n"
                f"━━━━━━━━━━━━━━\n"
                f"📚 **العدد:** `{count}`\n"
                f"💾 **الحجم:** `{size_fmt}`\n"
                f"━━━━━━━━━━━━━━\n"
                f"💡 عند الانتهاء أرسل **/done**"
            )

            # أول ملف؟ ابعت رسالة فوراً
            if sess.msg is None:
                sess.msg = await message.reply_text(text)
                sess.last_update = time.time()
            
            # ملفات تالية؟ حدث الرسالة كل 3 ثواني فقط (عشان التليجرام ميزعلش)
            elif time.time() - sess.last_update > 3:
                try:
                    await sess.msg.edit_text(text)
                    sess.last_update = time.time()
                except MessageNotModified:
                    pass
                except Exception:
                    # لو الرسالة القديمة اتمسحت، ابعت واحدة جديدة
                    sess.msg = await message.reply_text(text)

    except Exception as e:
        print(f"Error downloading: {e}")

# --- 2. إنهاء الاستلام (الحل الجذري لتكرار الرسالة) ---
@app.on_message(filters.command("done"))
async def done_cmd(client, message):
    uid = message.from_user.id
    if uid not in sessions:
        return await message.reply_text("❌ لم أستلم ملفات بعد.")

    sess = sessions[uid]

    # --- ⛔ قفل لمنع التكرار ⛔ ---
    # لو الحالة مش "تجميع"، معناها احنا ردينا عليه قبل كده -> اخرج فوراً
    if sess.state != 'collecting':
        return 

    # تغيير الحالة فوراً عشان لو ضغط تاني ميحصلش حاجة
    sess.state = 'waiting_name'

    # مسح رسالة العداد القديمة عشان الشات ينضف
    if sess.msg:
        try: await sess.msg.delete()
        except: pass
    
    await message.reply_text(
        f"✅ **تم قفل القائمة: {len(sess.files)} ملف.**\n"
        f"🔖 **أرسل اسم الملف النهائي الآن:**"
    )

# --- 3. الدمج والرفع (الأخير) ---
@app.on_message(filters.text & ~filters.command(["start", "done"]))
async def process(client, message):
    uid = message.from_user.id
    sess = sessions.get(uid)
    
    if not sess or sess.state != 'waiting_name': return

    # تجهيز الاسم
    fname = message.text.strip().replace('/', '-')
    if not fname.endswith('.pdf'): fname += ".pdf"

    sess.state = 'processing' # قفل نهائي
    
    status = await message.reply_text("⏳ **جاري الترتيب والدمج...**")
    out_path = f"downloads/{uid}/{fname}"

    # عملية الدمج في الخلفية
    def do_merge():
        merger = PdfMerger()
        sess.files.sort(key=natural_key) # الترتيب السحري
        for f in sess.files: merger.append(f)
        merger.write(out_path)
        merger.close()

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, do_merge)
    except Exception as e:
        return await status.edit_text(f"❌ ملف تالف: {e}")

    # الرفع مع شريط تقدم
    await status.edit_text("🚀 **جاري الرفع... 0%**")
    
    last_p_time = 0
    async def prog(cur, tot):
        nonlocal last_p_time
        # تحديث كل 4 ثواني فقط
        if time.time() - last_p_time < 4 and cur != tot: return
        last_p_time = time.time()
        
        try:
            p = (cur/tot)*100
            await status.edit_text(f"🚀 **جاري الرفع... {p:.1f}%**")
        except: pass

    try:
        await client.send_document(
            message.chat.id,
            document=out_path,
            caption=f"📦 **{fname}**\n🗂 عدد الفصول: {len(sess.files)}",
            progress=prog
        )
        await status.delete()
        await message.reply_text("✅ **تم! أرسل /start لبدء جديد.**")
    except Exception as e:
        await status.edit_text(f"❌ خطأ الرفع: {e}")
    
    # تنظيف
    shutil.rmtree(f"downloads/{uid}", ignore_errors=True)
    del sessions[uid]

# Flask Stay-Alive
app_web = Flask(__name__)
@app_web.route('/')
def i(): return "ON"
def r(): app_web.run(host='0.0.0.0', port=8080)

if __name__ == '__main__':
    Thread(target=r, daemon=True).start()
    app.run()
