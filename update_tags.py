import os
import base64
import pickle
import random
import time
import inspect  # جديد: لفحص تواقيع الدوال
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# الإعدادات الأساسية
CLIENT_SECRET_JSON_B64 = os.environ.get("CLIENT_SECRET_JSON_B64")
TOKEN_PICKLE_B64 = os.environ.get("TOKEN_PICKLE_B64")
TRENDSMCP_API_KEY = os.environ.get("TRENDSMCP_API_KEY")
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
MAX_TAGS_PER_VIDEO = 10

# ============================================
# 🧠 دالة جلب الكلمات الرائجة (مع تشخيص نهائي)
# ============================================
def get_trending_keywords():
    print("📈 جارٍ جلب الكلمات الرائجة من Trends MCP...")
    try:
        from trendsmcp import TrendsMcpClient, GetTopTrendsParams
        
        # طباعة توقيع GetTopTrendsParams لمعرفة اسماء الوسائط
        print("DEBUG: توقيع GetTopTrendsParams:")
        sig = inspect.signature(GetTopTrendsParams.__init__)
        for name, param in sig.parameters.items():
            if name != 'self':
                print(f"  - {name}: type={param.annotation}, default={param.default}")
        
        # بناء params بناءً على الاسماء التي ستظهر
        # سنحاول تخمين الاسم الصحيح بناءً على شيوع `source`, `query`, `term`, `keyword`, إلخ
        params = None
        param_names = [p for p in sig.parameters.keys() if p != 'self']
        
        # محاولة أولى: إذا كان هناك وسيط اسمه 'query' أو 'keyword' أو 'term'
        if 'query' in param_names:
            params = GetTopTrendsParams(query='youtube', geo='SA', limit=20)
        elif 'keyword' in param_names:
            params = GetTopTrendsParams(keyword='youtube', geo='SA', limit=20)
        elif 'term' in param_names:
            params = GetTopTrendsParams(term='youtube', geo='SA', limit=20)
        elif 'source' in param_names:
            params = GetTopTrendsParams(source='youtube', geo='SA', limit=20)
        else:
            # طباعة رسالة للمساعدة
            print("DEBUG: لم يتم التعرف على اسم وسيط المصدر. الأسماء المتاحة:")
            for n in param_names:
                print(f"  {n}")
            raise ValueError("يجب تحديد اسم وسيط المصدر يدوياً")
        
        client = TrendsMcpClient(api_key=TRENDSMCP_API_KEY)
        response = client.get_top_trends(params)
        print(f"DEBUG: نوع الرد: {type(response)}")
        print(f"DEBUG: محتوى الرد: {response}")
        
        if response and hasattr(response, 'data') and response.data:
            keywords = [item.term for item in response.data if hasattr(item, 'term') and item.term]
            if keywords:
                print(f"✅ تم جلب {len(keywords)} كلمة رائجة من YouTube السعودية.")
                return keywords
        
        raise ValueError("لم يتم العثور على كلمات في الرد")
        
    except Exception as e:
        print(f"⚠️ خطأ أثناء جلب الكلمات الرائجة: {e}")
        print("🔁 سيتم استخدام قائمة احتياطية ديناميكية.")
        fallback = [
            "تقنية", "ذكاء اصطناعي", "ألعاب", "يوتيوب", "تيك توك",
            "كرة قدم", "مسلسلات", "أفلام", "تسويق", "استثمار",
            "عملات رقمية", "بيتكوين", "أسهم", "تعليم", "جامعة",
            "منح دراسية", "لغات", "إنجليزي", "صحة", "رياضة",
            "طبخ", "وصفات", "سيارات", "سفر", "سياحة", "أخبار",
            "سياسة", "اقتصاد", "تاريخ", "علوم", "فضاء", "كتب",
            "قراءة", "روايات", "شعر", "فن", "رسم", "موسيقى",
            "موضة", "مكياج", "عناية بالبشرة", "لياقة", "تغذية",
            "حيوانات", "طبيعة", "بحر", "جبال", "غابات", "تكنولوجيا",
            "روبوتات", "واقع افتراضي", "بلوك تشين", "تطبيقات",
            "جوجل", "مايكروسوفت", "آبل", "سامسونج", "هواوي",
            "العمل الحر", "ربح من الإنترنت", "تجارة إلكترونية",
            "مهارات", "تنمية بشرية", "تحفيز", "إدارة وقت", "إنتاجية",
            "تصوير", "كاميرات", "فيديو", "بث مباشر", "ستريمر",
            "قيمر", "شروحات", "مراجعات", "نصائح", "حيل",
            "خدع", "تجارب", "تحليل", "مقابلات", "بودكاست",
            "قصص", "حكايات", "طرائف", "تحديات", "مسابقات",
            "تبرعات", "خير", "تطوع", "بيئة", "مناخ",
            "طاقة متجددة", "كهرباء", "إلكترونيات", "أدوات",
            "بناء", "نجارة", "زراعة", "حدائق", "أزهار",
            "ديكور", "أثاث", "تنظيف", "تنظيم"
        ]
        return random.sample(fallback, min(20, len(fallback)))

# باقي الدوال (دالة المصادقة، جلب الفيديوهات، تحديث الكلمات) دون تغيير
# ... (أنقلها كما هي من الكود السابق)
# سأضع كود الدوال الكامل ليكون الملف مكتملاً

# ============================================
# 🔐 دالة المصادقة
# ============================================
def get_authenticated_service():
    if not TOKEN_PICKLE_B64:
        raise ValueError("TOKEN_PICKLE_B64 غير موجود")
    token_bytes = base64.b64decode(TOKEN_PICKLE_B64)
    credentials = pickle.loads(token_bytes)
    if credentials.expired and credentials.refresh_token:
        print("🔄 جارٍ تجديد الجلسة تلقائياً...")
        credentials.refresh(Request())
        print("✅ تم تجديد الجلسة بنجاح.")
    return build('youtube', 'v3', credentials=credentials)

# ============================================
# 📋 دالة جلب الفيديوهات
# ============================================
def get_all_channel_videos(youtube):
    try:
        request = youtube.channels().list(part="id", mine=True)
        response = request.execute()
        channel_id = response['items'][0]['id']
        print(f"📺 معرف القناة: {channel_id}")
    except HttpError as e:
        print(f"❌ خطأ: {e}")
        return []
    videos = []
    next_page_token = None
    print("🔍 جارٍ جلب الفيديوهات...")
    while True:
        try:
            search_request = youtube.search().list(
                part="id,snippet", channelId=channel_id,
                maxResults=50, pageToken=next_page_token, type="video"
            )
            search_response = search_request.execute()
            for item in search_response.get('items', []):
                video_id = item['id']['videoId']
                video_title = item['snippet']['title']
                videos.append((video_id, video_title))
            next_page_token = search_response.get('nextPageToken')
            if not next_page_token:
                break
            print(f"   📄 تم جلب {len(videos)} فيديو...")
        except HttpError as e:
            print(f"❌ خطأ: {e}")
            break
    print(f"🎉 إجمالي الفيديوهات: {len(videos)}")
    return videos

# ============================================
# ✍️ دالة تحديث الكلمات
# ============================================
def update_video_tags(youtube, video_id, video_title, new_tags):
    try:
        video_request = youtube.videos().list(part="snippet", id=video_id)
        video_response = video_request.execute()
        if not video_response['items']:
            return False
        snippet = video_response['items'][0]['snippet']
        snippet['tags'] = new_tags
        update_request = youtube.videos().update(
            part="snippet", body={"id": video_id, "snippet": snippet}
        )
        update_request.execute()
        print(f"   ✅ تم تحديث: {video_title[:50]}...")
        return True
    except HttpError as e:
        print(f"   ❌ فشل: {e}")
        return False

# ============================================
# 🚀 الدالة الرئيسية
# ============================================
def main():
    print("🚀 بدء سكربت تحديث الكلمات المفتاحية - وضع الترند")

    trending_keywords = get_trending_keywords()
    final_tags = random.sample(trending_keywords, min(len(trending_keywords), MAX_TAGS_PER_VIDEO))
    print(f"📝 الكلمات المفتاحية الجديدة: {final_tags}")

    youtube = get_authenticated_service()
    videos = get_all_channel_videos(youtube)
    if not videos:
        return

    success = 0
    for idx, (vid, title) in enumerate(videos, 1):
        print(f"[{idx}/{len(videos)}] {vid}")
        if update_video_tags(youtube, vid, title, final_tags):
            success += 1
        time.sleep(0.5)

    print(f"📊 تم تحديث {success} من {len(videos)} فيديو بنجاح.")

if __name__ == "__main__":
    main()
