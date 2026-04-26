import os
import base64
import pickle
import random
import time
import urllib.request
import xml.etree.ElementTree as ET
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# الإعدادات الأساسية
CLIENT_SECRET_JSON_B64 = os.environ.get("CLIENT_SECRET_JSON_B64")
TOKEN_PICKLE_B64 = os.environ.get("TOKEN_PICKLE_B64")
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
MAX_TAGS_PER_VIDEO = 10

# ============================================
# 🧠 دالة جلب الكلمات الرائجة من Google Trends RSS
# ============================================
def get_trending_keywords():
    print("📈 جارٍ جلب الكلمات الرائجة من Google Trends RSS...")
    try:
        # رابط RSS الرسمي للترند في السعودية
        rss_url = "https://trends.google.com/trending/rss?geo=SA"
        
        # طلب البيانات من الرابط
        with urllib.request.urlopen(rss_url) as response:
            rss_data = response.read().decode('utf-8')
        
        # تحليل بيانات RSS
        root = ET.fromstring(rss_data)
        
        # استخراج العناوين
        keywords = []
        for item in root.findall('.//item/title'):
            title_text = item.text.strip()
            if title_text:
                keywords.append(title_text)
        
        if keywords:
            print(f"✅ تم جلب {len(keywords)} كلمة رائجة من السعودية.")
            return keywords
        else:
            raise ValueError("لم يتم العثور على أي كلمة رائجة في الـ RSS")
            
    except Exception as e:
        print(f"⚠️ خطأ أثناء جلب الكلمات الرائجة: {e}")
        print("🔁 سيتم استخدام قائمة احتياطية ديناميكية.")
        fallback = [
            "تقنية", "ذكاء اصطناعي", "ألعاب", "يوتيوب", "تيك توك",
            "كرة قدم", "مسلسلات", "أفلام", "تسويق", "استثمار",
            "عملات رقمية", "أسهم", "تعليم", "جامعة", "صحة",
            "رياضة", "طبخ", "سيارات", "سفر", "سياحة",
            "تاريخ", "علوم", "فضاء", "كتب", "فن",
            "موضة", "مكياج", "لياقة", "تغذية", "حيوانات",
            "روبوتات", "تطبيقات", "جوجل", "آبل", "سامسونج",
            "ربح من الإنترنت", "تجارة إلكترونية", "مهارات", "إنتاجية", "تصوير",
            "فيديو", "بث مباشر", "شروحات", "مراجعات", "نصائح",
            "تجارب", "تحليل", "بودكاست", "قصص", "تحديات",
            "بيئة", "مناخ", "طاقة", "ديكور", "تنظيم"
        ]
        return random.sample(fallback, min(20, len(fallback)))

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
