import os, base64, pickle, random, time, re, json
import urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ============ الإعدادات ============
CLIENT_SECRET_JSON_B64 = os.environ.get("CLIENT_SECRET_JSON_B64")
TOKEN_PICKLE_B64 = os.environ.get("TOKEN_PICKLE_B64")
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
MAX_TAGS_PER_VIDEO = 15
MAX_VIDEOS_PER_RUN = 1 # فيديو واحد يومياً
DAYS_BETWEEN_UPDATES = 14 # لا يحدث الفيديو إلا كل 14 يوم
LOG_FILE = 'update_log.json' # نسجل هنا متى حدثنا كل فيديو

# ============ جلب ترند السعودية ============
def get_trending_keywords():
    print("📈 جارٍ جلب ترند السعودية اليوم...")
    try:
        rss_url = "https://trends.google.com/trending/rss?geo=SA"
        with urllib.request.urlopen(rss_url) as response:
            rss_data = response.read().decode('utf-8')
        root = ET.fromstring(rss_data)
        keywords = []
        for item in root.findall('.//item'):
            title = item.find('title').text.strip()
            desc = item.find('description').text.strip()
            keywords.append(title)
            keywords.extend(re.findall(r'[\u0600-\u06FF]+', desc)[:2])
        return list(dict.fromkeys(keywords))[:20]
    except Exception as e:
        print(f"⚠️ خطأ بالترند: {e}")
        return ["السعودية", "ترند_اليوم", "جديد", "2026"]

# ============ تسجيل الدخول ============
def get_authenticated_service():
    token_bytes = base64.b64decode(TOKEN_PICKLE_B64)
    credentials = pickle.loads(token_bytes)
    if credentials.expired and credentials.refresh_token:
        print("🔄 تجديد الجلسة...")
        credentials.refresh(Request())
    return build('youtube', 'v3', credentials=credentials)

# ============ قراءة وكتابة السجل ============
def load_update_log():
    try:
        with open(LOG_FILE, 'r') as f:
            return json.load(f)
    except:
        return {} # لو أول مرة يشتغل

def save_update_log(log):
    with open(LOG_FILE, 'w') as f:
        json.dump(log, f)

# ============ جلب فيديو محتاج تحديث ============
def get_video_to_update(youtube, update_log):
    request = youtube.channels().list(part="contentDetails", mine=True)
    response = request.execute()
    uploads_id = response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

    request = youtube.playlistItems().list(
        part="snippet", playlistId=uploads_id, maxResults=50
    )
    response = request.execute()

    videos = []
    today = datetime.now()
    cutoff_date = today - timedelta(days=DAYS_BETWEEN_UPDATES)

    for item in response['items']:
        vid = item['snippet']['resourceId']['videoId']
        title = item['snippet']['title']
        published = item['snippet']['publishedAt']

        # نشوف متى آخر مرة حدثناه
        last_update_str = update_log.get(vid)
        if last_update_str:
            last_update = datetime.fromisoformat(last_update_str)
            if last_update > cutoff_date:
                continue # لسه ما كمل 14 يوم، نطنشه

        videos.append((vid, title, published, last_update_str))

    # نرتبهم: اللي ما تحدث أبد أول، بعدين الأقدم تحديثاً
    videos.sort(key=lambda x: x[3] or '2000-01-01')
    return videos[:MAX_VIDEOS_PER_RUN]

# ============ اختيار تاقات ذكية ============
def smart_tag_selection(video_title, all_trends):
    video_words = set(re.findall(r'[\u0600-\u06FF\w]+', video_title.lower()))
    related_tags = []
    for trend in all_trends:
        trend_words = set(re.findall(r'[\u0600-\u06FF\w]+', trend.lower()))
        if video_words & trend_words:
            related_tags.append(trend)
    if not related_tags:
        related_tags = random.sample(all_trends, min(3, len(all_trends)))
    return related_tags[:MAX_TAGS_PER_VIDEO]

# ============ تحديث الفيديو ============
def update_video(youtube, video_id, video_title, new_tags):
    try:
        req = youtube.videos().list(part="snippet", id=video_id)
        res = req.execute()
        if not res['items']:
            return False, "الفيديو غير موجود"

        snippet = res['items'][0]['snippet']
        old_tags = snippet.get('tags', [])
        old_desc = snippet.get('description', '')

        # 1. نحدث التاقات - نحذف القديمة ونحط الجديدة
        snippet['tags'] = new_tags[:MAX_TAGS_PER_VIDEO]

        # 2. نحدث الوصف - نحذف سطر الترند القديم ونحط الجديد
        if new_tags:
            today_str = datetime.now().strftime("%Y-%m-%d")
            trend_hashtag = " ".join([f"#{tag.replace(' ', '_')}" for tag in new_tags[:3]])
            new_first_line = f"{trend_hashtag} | تحديث {today_str}\n\n"

            # نحذف أول 3 أسطر لو كانت تحديث قديم
            desc_lines = old_desc.split('\n')
            if desc_lines and ('ترند' in desc_lines[0] or 'تحديث' in desc_lines[0]):
                old_desc = '\n'.join(desc_lines[3:])

            snippet['description'] = new_first_line + old_desc

        youtube.videos().update(part="snippet", body={"id": video_id, "snippet": snippet}).execute()
        return True, f"تم تحديث: {video_title[:40]}"
    except HttpError as e:
        return False, f"خطأ: {e}"

# ============ التشغيل الرئيسي ============
if __name__ == "__main__":
    print("🚀 بدء التحديث الذكي...")
    yt = get_authenticated_service()
    trends = get_trending_keywords()
    update_log = load_update_log()

    videos = get_video_to_update(yt, update_log)

    if not videos:
        print("✅ كل الفيديوهات محدثة خلال آخر 14 يوم. ما يحتاج شغل اليوم")
    else:
        for vid, title, _, _ in videos:
            tags = smart_tag_selection(title, trends)
            success, msg = update_video(yt, vid, title, tags)
            print(msg)
            if success:
                # نسجل تاريخ التحديث
                update_log[vid] = datetime.now().isoformat()
                save_update_log(update_log)
            time.sleep(3)

    print("🎉 انتهى التشغيل")
