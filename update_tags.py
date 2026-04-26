import os
import base64
import pickle
import random
import time
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ============================================
# الإعدادات الأساسية
# ============================================
CLIENT_SECRET_JSON_B64 = os.environ.get("CLIENT_SECRET_JSON_B64")
TOKEN_PICKLE_B64 = os.environ.get("TOKEN_PICKLE_B64")
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
MAX_TAGS_PER_VIDEO = 10

# ============================================
# دالة جلب الكلمات المفتاحية الديناميكية
# ============================================
def get_dynamic_tags():
    print("📈 جارٍ تجهيز الكلمات المفتاحية الديناميكية...")
    base_keywords = [
        "تقنية", "ذكاء اصطناعي", "تعلم الآلة", "برمجة", "بايثون", "تطوير الويب",
        "أمن سيبراني", "يوتيوب", "تيك توك", "إنترنت", "هواتف", "آيفون", "أندرويد",
        "ألعاب", "فيفا", "ببجي", "تصميم", "فوتوشوب", "مونتاج", "تدوين", "تسويق",
        "استثمار", "عملات رقمية", "بيتكوين", "أسهم", "ريادة أعمال", "تعليم", "جامعة",
        "منح دراسية", "لغات", "إنجليزي", "تعلم", "صحة", "رياضة", "كرة قدم", "تمارين",
        "طبخ", "وصفات", "سيارات", "سفر", "سياحة", "طقس", "أخبار", "سياسة", "اقتصاد",
        "تاريخ", "جغرافيا", "علوم", "فيزياء", "كيمياء", "أحياء", "فضاء", "نجوم",
        "كتب", "قراءة", "روايات", "شعر", "فن", "رسم", "موسيقى", "غناء", "عزف",
        "مسلسلات", "أفلام", "دراما", "كوميديا", "أنمي", "كرتون", "مانجا",
        "موضة", "أزياء", "مكياج", "عناية بالبشرة", "لياقة", "تغذية", "رجيم",
        "حيوانات", "قطط", "كلاب", "طيور", "طبيعة", "بحر", "جبال", "غابات",
        "تكنولوجيا", "روبوتات", "واقع افتراضي", "ميتافيرس", "بلوك تشين",
        "تطبيقات", "جوجل", "مايكروسوفت", "آبل", "سامسونج", "هواوي",
        "العمل الحر", "ربح من الإنترنت", "تجارة إلكترونية", "دروس خصوصية",
        "مهارات", "تنمية بشرية", "تحفيز", "إدارة وقت", "إنتاجية", "تخطيط",
        "تصوير", "كاميرات", "عدسات", "فيديو", "بث مباشر", "ستريمر", "قيمر",
        "شروحات", "مراجعات", "نصائح", "حيل", "خدع", "تجارب", "تحليل",
        "مقابلات", "بودكاست", "قصص", "حكايات", "طرائف", "مواقف", "تحديات",
        "مسابقات", "جوائز", "تبرعات", "خير", "تطوع", "بيئة", "مناخ",
        "طاقة متجددة", "كهرباء", "إلكترونيات", "أدوات", "بناء", "نجارة",
        "زراعة", "حدائق", "أزهار", "ديكور", "أثاث", "تنظيف", "تنظيم"
    ]
    keywords = random.sample(base_keywords, min(20, len(base_keywords)))
    print(f"✅ تم اختيار {len(keywords)} كلمة.")
    return keywords

# ============================================
# دالة المصادقة
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
# دالة جلب الفيديوهات
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
# دالة تحديث الكلمات
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
# الدالة الرئيسية
# ============================================
def main():
    print("🚀 بدء سكربت تحديث الكلمات الذكي")
    
    dynamic_keywords = get_dynamic_tags()
    final_tags = random.sample(dynamic_keywords, min(len(dynamic_keywords), MAX_TAGS_PER_VIDEO))
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
    
    print(f"📊 تم تحديث {success} من {len(videos)} فيديو.")

if __name__ == "__main__":
    main()
