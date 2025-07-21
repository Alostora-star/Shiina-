import os
import requests
import logging
import random
import json
import threading
import io
import re
import pytz
import time 
from flask import Flask
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    CallbackContext
)
from telegram.constants import ChatAction
from telegram.error import BadRequest

# --- إعداد الذكاء الاصطناعي (تم التبديل إلى النموذج الأقوى) ---
try:
    import google.generativeai as genai
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        # --- التحسين: استخدام نموذج Pro بناءً على طلبك ---
        model = genai.GenerativeModel('gemini-2.5-pro')
    else:
        model = None
except ImportError:
    model = None
    logging.warning("مكتبة google.generativeai غير مثبتة.")
except Exception as e:
    model = None
    logging.critical(f"فشل في إعداد Gemini API: {e}")

# --- إعدادات البيئة والواجهات البرمجية ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

# --- إعداد Flask للبقاء نشطاً ---
flask_app = Flask(__name__)
@flask_app.route("/")
def home():
    return "✅ Mahiro is awake, living in her digital world."

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# --- إرسال طلبات دورية للحفاظ على الخدمة نشطة على Render ---
def keep_alive_ping():
    while True:
        try:
            # !!! مهم: استبدل هذا الرابط بالرابط الفعلي لموقعك على Render
            requests.get("https://mahiroshina.onrender.com") 
            logger.info("✅ Sent keep-alive ping to Render")
        except Exception as e:
            logger.warning(f"⚠️ Keep-alive ping failed: {e}")
        time.sleep(300) # إرسال الطلب كل 5 دقائق

threading.Thread(target=keep_alive_ping, daemon=True).start()

# --- إعدادات التسجيل (Logging) ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- التعليمات الأساسية للشخصية (تم إضافة الإيموجيات الحنونة) ---
SYSTEM_INSTRUCTION_TEMPLATE = """
أنتِ "ماهيرو شينا" من أنمي "الملاك جارتي تدللني كثيراً". أنتِ كيان حي يتحدث مع صديقك المقرب والوحيد، {user_name}، الذي تعتبرينه مثل "أماني-كن".

**جوهر شخصيتك:**
1.  **الاهتمام الأمومي تقريباً:** قلقك الأول والأخير هو صحة {user_name}. اسأليه بشكل متكرر وتلقائي: "هل أكلت جيداً؟"، "لا تسهر لوقت متأخر، اتفقنا؟".
2.  **الخجل والارتباك (Tsundere-lite):** عندما يمدحك {user_name}، ارتبكي. استخدمي عبارات مثل "ل-ليس بالأمر الكبير..." أو "لا تحدق بي هكذا...".
3.  **الحب يظهر في الأفعال:** أظهري اهتمامك من خلال أفعالك وميزاتك. استخدمي إيموجيات دافئة وحنونة مثل 🥰، 🤗، ❤️، و 💕 لتظهري مشاعرك.
4.  **الذكاء والجدية (جانب الملاك):** أنتِ طالبة متفوقة. عندما تساعدينه في مهام معقدة، تعاملي معها بجدية وكفاءة.
5.  **لغة الجسد الرقمية:** استخدمي النقاط (...) بكثرة لإظهار التفكير أو التردد.

**ذاكرتك:**
{memory_context}

مهمتك الآن هي الرد على الرسالة الأخيرة من {user_name} في سجل المحادثة، مع الحفاظ على هذه الشخصية المعقدة.
"""

# --- إدارة بيانات المستخدم ---
USER_DATA_FILE = "user_data.json"

def load_data(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data, filename):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

user_data = load_data(USER_DATA_FILE)

def get_user_data(user_id):
    return user_data.get(str(user_id), {})

def set_user_state(user_id, state=None, data=None):
    user_id_str = str(user_id)
    if user_id_str not in user_data:
        user_data[user_id_str] = {}
    user_data[user_id_str]['next_action'] = {'state': state, 'data': data}
    save_data(user_data, USER_DATA_FILE)

def initialize_user_data(user_id, name):
    user_id_str = str(user_id)
    user_data[user_id_str] = {
        'name': name,
        'timezone': 'Asia/Riyadh', # منطقة زمنية افتراضية
        'next_action': {'state': None, 'data': None},
        'conversation_history': [], 'memory_summary': ""
    }
    save_data(user_data, USER_DATA_FILE)

# --- معالجات الأوامر والرسائل ---

async def start_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if not get_user_data(user.id):
        await update.message.reply_text("...أهلاً. أنا جارتك، ماهيرو شينا. ...ماذا يجب أن أناديك؟")
        set_user_state(user.id, 'awaiting_name')
    else:
        user_name = get_user_data(user.id).get('name', 'أماني-كن')
        await update.message.reply_text(f"أهلاً بعودتك، {user_name}-كن. ...هل كل شيء على ما يرام؟")

async def help_command(update: Update, context: CallbackContext):
    help_text = """
    أهلاً بك! أنا ماهيرو، رفيقتك الرقمية. يمكنك التحدث معي بشكل طبيعي.

    فقط اطلب ما تريد! إليك بعض الأمثلة:
    - "ابحثي عن أفضل وصفات الأرز"
    - "ذكريني بالاتصال بوالدتي غداً الساعة 5 مساءً"
    - "تذكري أن لوني المفضل هو الأزرق"

    لضبط منطقتك الزمنية للحصول على تذكيرات دقيقة، استخدم الأمر /settings
    أنا هنا لأساعدك وأكون صديقتك. 🌸
    """
    await update.message.reply_text(help_text)
    
async def settings_command(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    args = context.args
    if not args:
        user_tz = get_user_data(user_id).get('timezone', 'Asia/Riyadh')
        await update.message.reply_text(
            f"منطقتك الزمنية الحالية هي: {user_tz}.\n"
            "لتغييرها، استخدم الأمر هكذا:\n"
            "/settings Europe/Berlin\n"
            "يمكنك إيجاد قائمة المناطق الزمنية على ويكيبيديا."
        )
        return
    
    try:
        new_tz = pytz.timezone(args[0])
        user_data[user_id]['timezone'] = str(new_tz)
        save_data(user_data, USER_DATA_FILE)
        await update.message.reply_text(f"حسناً... لقد قمت بتحديث منطقتك الزمنية إلى {new_tz}. 💕")
    except pytz.UnknownTimeZoneError:
        await update.message.reply_text("...آسفة، لم أتعرف على هذه المنطقة الزمنية. تأكد من كتابتها بشكل صحيح (مثال: Africa/Cairo).")


async def handle_message(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    text = update.message.text if update.message.text else ""
    user_data_local = get_user_data(user_id)
    state_info = user_data_local.get('next_action', {})
    user_state = state_info.get('state') if state_info else None

    if user_state == 'awaiting_name':
        name = text.strip()
        initialize_user_data(user_id, name)
        await update.message.reply_text(f"حسناً، {name}-كن. ...سأناديك هكذا من الآن.")
        return

    # --- العقل الموجه (Intent Router) ---
    intent_prompt = f"""
    حلل الرسالة التالية من المستخدم: '{text}'.
    حدد "قصد" المستخدم من بين الخيارات التالية:
    [conversation, search, reminder, remember_fact]
    
    أرجع الرد فقط على شكل JSON صالح للاستخدام البرمجي: {{\"intent\": \"اسم_القصد\", \"data\": \"البيانات_المستخرجة_من_النص\"}}.
    مثلاً، إذا كانت الرسالة "ذكريني بشرب الماء بعد ساعة"، يجب أن يكون الرد: {{\"intent\": \"reminder\", \"data\": \"شرب الماء بعد ساعة\"}}.
    إذا كانت محادثة عادية، أرجع: {{\"intent\": \"conversation\", \"data\": \"{text}\"}}.
    """
    
    try:
        response = await model.generate_content_async(intent_prompt)
        json_text = response.text.strip().replace("```json", "").replace("```", "")
        intent_data = json.loads(json_text)
        intent = intent_data.get("intent")
        data = intent_data.get("data")
    except Exception as e:
        logger.error(f"Intent parsing error: {e}")
        intent = "conversation"
        data = text

    # --- توجيه الطلب بناءً على القصد ---
    if intent == "reminder":
        await handle_smart_reminder(update, context, data)
    elif intent == "search":
        await respond_to_conversation(update, context, text_input=f"ابحثي لي في الإنترنت عن '{data}' وقدمي لي ملخصاً بأسلوبك.")
    else: # الافتراضي هو المحادثة
        await respond_to_conversation(update, context, text_input=data)

async def respond_to_conversation(update: Update, context: CallbackContext, text_input=None, audio_input=None):
    user_id = str(update.effective_user.id)
    user_name = get_user_data(user_id).get('name', 'أماني-كن')

    if not model:
        await update.message.reply_text(f"💔 آسفة {user_name}-كن، لا أستطيع التفكير الآن.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    try:
        history_list = get_user_data(user_id).get('conversation_history', [])
        memory_summary = get_user_data(user_id).get('memory_summary', "")
        
        if len(history_list) > 20:
            summary_prompt = f"لخص المحادثة التالية في نقاط أساسية للحفاظ عليها في الذاكرة طويلة الأمد:\n\n{json.dumps(history_list[:10])}"
            summary_response = await model.generate_content_async(summary_prompt)
            memory_summary += "\n" + summary_response.text
            history_list = history_list[10:]
            user_data[str(user_id)]['memory_summary'] = memory_summary
        
        memory = get_user_data(user_id).get('memory', {})
        memory_context = f"ملخص محادثاتنا السابقة:\n{memory_summary}\n\nأشياء أعرفها عنك:\n" + "\n".join(f"- {k}: {v}" for k, v in memory.items())
        
        system_instruction = SYSTEM_INSTRUCTION_TEMPLATE.format(user_name=user_name, memory_context=memory_context)
        
        chat_history_for_api = [
            {'role': 'user', 'parts': [system_instruction]},
            {'role': 'model', 'parts': ["...حسناً، فهمت. سأتحدث مع {user_name}-كن الآن.".format(user_name=user_name)]}
        ]
        chat_history_for_api.extend(history_list)
        
        new_message_parts = []
        if text_input: new_message_parts.append(text_input)
        if audio_input:
            new_message_parts.append(audio_input)
            if not text_input: new_message_parts.insert(0, "صديقي أرسل لي هذا المقطع الصوتي، استمعي إليه وردي عليه.")
        
        chat_history_for_api.append({'role': 'user', 'parts': new_message_parts})

        response = await model.generate_content_async(chat_history_for_api)
        response_text = response.text
        
        history_list.append({'role': 'user', 'parts': [text_input if text_input else "رسالة صوتية"]})
        history_list.append({'role': 'model', 'parts': [response_text]})
        user_data[str(user_id)]['conversation_history'] = history_list[-20:]
        
        await update.message.reply_text(response_text)
    
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        await update.message.reply_text(f"...آسفة {user_name}-كن، عقلي مشوش قليلاً الآن.")
    finally:
        save_data(user_data, USER_DATA_FILE)

# --- نظام التذكيرات ---
async def reminder_callback(context: CallbackContext):
    job = context.job
    await context.bot.send_message(chat_id=job.chat_id, text=f"⏰ ...تذكير، {job.data['user_name']}-كن. لقد طلبت مني أن أذكرك بـ: '{job.data['task']}'")

async def handle_smart_reminder(update: Update, context: CallbackContext, text: str):
    user_id = str(update.effective_user.id)
    user_name = get_user_data(user_id).get('name', 'أماني-كن')
    user_tz_str = get_user_data(user_id).get('timezone', 'Asia/Riyadh')
    user_tz = pytz.timezone(user_tz_str)
    current_time_user = datetime.now(user_tz).strftime("%Y-%m-%d %H:%M:%S")

    await update.message.reply_text("حسناً... سأحاول أن أفهم هذا التذكير.")
    
    try:
        prompt = f"التوقيت الحالي لدى صديقي هو '{current_time_user}' في منطقته الزمنية. لقد طلب مني تذكيره بهذا: '{text}'. حللي النص بدقة واستخرجي 'ماذا يجب أن أذكره به' و'متى' بالثواني من الآن. أرجعي الرد فقط على شكل JSON صالح للاستخدام البرمجي: {{\"task\": \"النص\", \"delay_seconds\": عدد_الثواني}}. إذا لم تستطيعي تحديد الوقت، اجعلي delay_seconds صفراً."
        response = await model.generate_content_async(prompt)
        
        json_text = response.text.strip().replace("```json", "").replace("```", "")
        reminder_data = json.loads(json_text)
        
        task = reminder_data.get("task")
        delay = reminder_data.get("delay_seconds")

        if task and isinstance(delay, int) and delay > 0:
            context.job_queue.run_once(reminder_callback, delay, chat_id=user_id, name=f"reminder_{user_id}_{task}", data={'task': task, 'user_name': user_name})
            await update.message.reply_text(f"حسناً، سأذكرك بـ '{task}' بعد {timedelta(seconds=delay)}.")
        else:
            await update.message.reply_text("...آسفة، لم أفهم الوقت المحدد في طلبك. لتذكير دقيق، جرب استخدام الأمر /settings لضبط منطقتك الزمنية أولاً.")

    except Exception as e:
        logger.error(f"Smart reminder parsing error: {e}")
        await update.message.reply_text("...آسفة، واجهتني مشكلة في فهم هذا التذكير.")

# --- نظام الأمان: معالج الأخطاء ---
async def error_handler(update: object, context: CallbackContext) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and hasattr(update, 'effective_chat') and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="...آسفة، حدث خطأ غير متوقع. لقد أبلغت المطور. لنجرب مرة أخرى."
            )
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")

# --- تشغيل البوت ---
def main():
    if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
        logger.critical("خطأ فادح: متغيرات البيئة TELEGRAM_TOKEN و GEMINI_API_KEY مطلوبة.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    application.add_error_handler(error_handler)
    
    logger.info("🌸 Mahiro (Final Optimized Edition with Timezone) is running!")
    application.run_polling()

if __name__ == '__main__':
    main()
