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
MAX_TAGS_PER_VIDEO = 12
MAX_VIDEOS_PER_RUN = 3  # 🔥 3 فيديوهات كل يوم
DAYS_BETWEEN_UPDATES = 7  # كل فيديو يتحدث كل أسبوع
LOG_FILE = 'update_log.json'
BANNED_WORDS = ['vs', 'espanyol', 'levante', 'lazio', 'udinese', 'fc', 'match', 'game', '2024', '2025', '2026', 'champions', 'league']
ARABIC_CHARS = re.compile(r'[\u0600-\u06FF]')

def get_trending_keywords():
    print("📈 جارٍ جلب ترند السعودية مع الفلترة...")
    try:
        rss_url = "https://trends.google.com/trending/rss?geo=SA"
        with urllib.request.urlopen(rss_url, timeout=10) as response:
            rss_data = response.read().decode('utf-8')
        root = ET.fromstring(rss_data)
        keywords = []
        for item in root.findall('.//item'):
            title_elem = item.find('title')
            desc_elem = item.find('description')
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
            desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""
            if title and ARABIC_CHARS.search(title):
                if not any(bad in title.lower() for bad in BANNED_WORDS):
                    keywords.append(title)
            if desc:
                arabic_words = re.findall(r'[\u0600-\u06FF]{3,}', desc)
                for word in arabic_words[:2]:
                    if not any(bad in word.lower() for bad in BANNED_WORDS):
                        keywords.append(word)
        final_keywords = list(dict.fromkeys(keywords))[:15]
        if not final_keywords:
            raise ValueError("ما لقينا ترند عربي")
        print(f"✅ ترند مفلتر: {final_keywords[:5]}...")
        return final_keywords
    except Exception as e:
        print(f"⚠️ خطأ بالترند: {e}. نستخدم قائمة احتياطية")
        return ["السعودية", "ترند", "جديد", "اكسبلور", "يومي", "السعودية_اليوم", "محتوى_عربي", "قصة", "تعليم"]

def get_authenticated_service():
    token_bytes = base64.b64decode(TOKEN_PICKLE_B64)
    credentials = pickle.loads(token_bytes)
    if credentials.expired and credentials.refresh_token:
        print("🔄 تجديد الجلسة...")
        credentials.refresh(Request())
    return build('youtube', 'v3', credentials=credentials)

def load_update_log():
    try:
        with open(LOG_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_update_log(log):
    with open(LOG_FILE, 'w') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

def get_videos_to_update(youtube, update_log):
    """
    تجلب جميع فيديوهات القناة (باستخدام pagination)،
    ثم تختار منها ما لم يتم تحديثه خلال آخر 7 أيام،
    وتعيد قائمة بأقدم الفيديوهات التي تحتاج تحديثاً (حسب تاريخ آخر تحديث).
    """
    # 1. معرفة قائمة الرفع الخاصة بالقناة
    request = youtube.channels().list(part="contentDetails", mine=True)
    response = request.execute()
    uploads_id = response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

    videos = []
    today = datetime.now()
    cutoff_date = today - timedelta(days=DAYS_BETWEEN_UPDATES)
    page_token = None

    # 2. جمع كل الفيديوهات باستخدام التصفح المتعدد (pagination)
    while True:
        req = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_id,
            maxResults=50,
            pageToken=page_token
        )
        res = req.execute()

        for item in res['items']:
            vid = item['snippet']['resourceId']['videoId']
            title = item['snippet']['title']
            published = item['snippet']['publishedAt']
            last_update_str = update_log.get(vid)

            # تجاهل الفيديوهات التي تم تحديثها خلال آخر 7 أيام
            if last_update_str:
                last_update = datetime.fromisoformat(last_update_str)
                if last_update > cutoff_date:
                    continue
            else:
                last_update = None  # لم تُحدّث مطلقاً

            videos.append((vid, title, published, last_update_str, last_update))

        page_token = res.get('nextPageToken')
        if not page_token:
            break

    # 3. ترتيب تصاعدي: الأقدم تحديثاً أولاً (None = الأقدم من الكل)
    videos.sort(key=lambda x: x[4] if x[4] is not None else datetime.min)

    # نأخذ العدد المطلوب
    top_videos = videos[:MAX_VIDEOS_PER_RUN]

    # نعيد البيانات من دون كائن last_update (نكتفي بالمعلومات الأصلية)
    return [(v[0], v[1], v[2], v[3]) for v in top_videos]

def smart_tag_selection(video_title, all_trends):
    video_words = set(re.findall(r'[\u0600-\u06FF]{3,}', video_title.lower()))
    related_tags = []
    for trend in all_trends:
        if not ARABIC_CHARS.search(trend): continue
        if any(bad in trend.lower() for bad in BANNED_WORDS): continue
        trend_words = set(re.findall(r'[\u0600-\u06FF]{3,}', trend.lower()))
        if video_words & trend_words:
            related_tags.append(trend)
    if len(related_tags) < 3:
        clean_trends = [t for t in all_trends if ARABIC_CHARS.search(t) and not any(bad in t.lower() for bad in BANNED_WORDS)]
        related_tags.extend(random.sample(clean_trends, min(4, len(clean_trends))))
    return list(dict.fromkeys(related_tags))[:MAX_TAGS_PER_VIDEO]

def update_video(youtube, video_id, video_title, new_tags):
    try:
        req = youtube.videos().list(part="snippet", id=video_id)
        res = req.execute()
        if not res['items']:
            return False, "الفيديو غير موجود"
        snippet = res['items'][0]['snippet']
        old_desc = snippet.get('description', '')
        snippet['tags'] = new_tags
        if new_tags:
            today_str = datetime.now().strftime("%m-%d")
            trend_hashtag = " ".join([f"#{tag.replace(' ', '_')}" for tag in new_tags[:3]])
            new_first_line = f"{trend_hashtag} | تحديث {today_str}\n\n"
            desc_lines = old_desc.split('\n')
            if desc_lines and ('ترند' in desc_lines[0] or 'تحديث' in desc_lines[0]):
                old_desc = '\n'.join(desc_lines[3:])
            snippet['description'] = new_first_line + old_desc
        youtube.videos().update(
            part="snippet",
            body={"id": video_id, "snippet": snippet}
        ).execute()
        return True, f"✅ {video_title[:35]} | تاقات: {new_tags[:3]}"
    except HttpError as e:
        return False, f"❌ خطأ: {e}"

if __name__ == "__main__":
    print("🚀 بدء التحديث الذكي V6 - 3 فيديوهات يومياً...")
    yt = get_authenticated_service()
    trends = get_trending_keywords()
    update_log = load_update_log()
    videos = get_videos_to_update(yt, update_log)

    print(f"🔍 لقينا {len(videos)} فيديو يحتاج تحديث")

    if not videos:
        print("✅ كل الفيديوهات محدثة آخر 7 أيام")
    else:
        print(f"🎯 بنحدث {len(videos)} فيديو اليوم")
        for vid, title, _, _ in videos:
            tags = smart_tag_selection(title, trends)
            success, msg = update_video(yt, vid, title, tags)
            print(msg)
            if success:
                update_log[vid] = datetime.now().isoformat()
                save_update_log(update_log)
            time.sleep(3)
    print("🎉 انتهى التشغيل")
