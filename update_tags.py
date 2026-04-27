import os, base64, pickle, random, time, re
import urllib.request, xml.etree.ElementTree as ET
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

CLIENT_SECRET_JSON_B64 = os.environ.get("CLIENT_SECRET_JSON_B64")
TOKEN_PICKLE_B64 = os.environ.get("TOKEN_PICKLE_B64")
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
MAX_TAGS_PER_VIDEO = 15 # زدنا العدد
MAX_VIDEOS_PER_RUN = 10 # عشان الكوتا ما تخلص

def get_trending_keywords():
    """نجيب ترند السعودية + الكلمات المتعلقة فيه"""
    print("📈 جارٍ جلب الكلمات الرائجة + المتعلقة...")
    try:
        rss_url = "https://trends.google.com/trending/rss?geo=SA"
        with urllib.request.urlopen(rss_url) as response:
            rss_data = response.read().decode('utf-8')
        root = ET.fromstring(rss_data)
        keywords = []
        # نجيب الترند + الوصف حقه لأن الوصف فيه كلمات بحث
        for item in root.findall('.//item'):
            title = item.find('title').text.strip()
            desc = item.find('description').text.strip()
            keywords.append(title)
            # نطلع كلمات من الوصف
            keywords.extend(re.findall(r'[\u0600-\u06FF]+', desc)[:2])

        # نشيل المكرر ونرجع أهم 20
        return list(dict.fromkeys(keywords))[:20]
    except Exception as e:
        print(f"⚠️ خطأ: {e}")
        return ["السعودية", "ترند", "جديد", "2026"]

def get_authenticated_service():
    token_bytes = base64.b64decode(TOKEN_PICKLE_B64)
    credentials = pickle.loads(token_bytes)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    return build('youtube', 'v3', credentials=credentials)

def get_recent_videos(youtube, max_results=10):
    """نجيب آخر 10 فيديوهات بس، مو كل القناة"""
    request = youtube.channels().list(part="contentDetails", mine=True)
    response = request.execute()
    uploads_id = response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

    request = youtube.playlistItems().list(
        part="snippet", playlistId=uploads_id, maxResults=max_results
    )
    response = request.execute()
    videos = []
    for item in response['items']:
        vid = item['snippet']['resourceId']['videoId']
        title = item['snippet']['title']
        videos.append((vid, title))
    return videos

def smart_tag_selection(video_title, all_trends):
    """نختار تاقات لها علاقة بعنوان الفيديو فقط"""
    video_words = set(re.findall(r'[\u0600-\u06FF\w]+', video_title.lower()))
    related_tags = []

    for trend in all_trends:
        trend_words = set(re.findall(r'[\u0600-\u06FF\w]+', trend.lower()))
        # لو فيه كلمة مشتركة بين العنوان والترند، نضيفه
        if video_words & trend_words:
            related_tags.append(trend)

    # لو ما لقينا علاقة، نحط 3 ترندات عامة بس
    if not related_tags:
        related_tags = random.sample(all_trends, min(3, len(all_trends)))

    return related_tags[:MAX_TAGS_PER_VIDEO]

def update_video(youtube, video_id, video_title, new_tags):
    try:
        req = youtube.videos().list(part="snippet", id=video_id)
        res = req.execute()
        if not res['items']: return False

        snippet = res['items'][0]['snippet']
        old_tags = snippet.get('tags', [])

        # ندمج القديم مع الجديد ونشيل المكرر
        final_tags = list(dict.fromkeys(old_tags + new_tags))[:MAX_TAGS_PER_VIDEO]
        snippet['tags'] = final_tags

        # 🔥 الحركة المهمة: نضيف الترند لأول سطر بالوصف
        if new_tags:
            trend_line = f"#{new_tags[0]} | "
            if not snippet['description'].startswith(trend_line):
                snippet['description'] = trend_line + snippet['description']

        youtube.videos().update(part="snippet", body={"id": video_id, "snippet": snippet}).execute()
        print(f"✅ {video_title[:30]}... | تاقات: {final_tags[:3]}...")
        return True
    except HttpError as e:
        print(f"❌ خطأ: {e}")
        return False

if __name__ == "__main__":
    yt = get_authenticated_service()
    trends = get_trending_keywords()
    videos = get_recent_videos(yt, MAX_VIDEOS_PER_RUN)

    print(f"🎯 بنحدث {len(videos)} فيديو بـ {len(trends)} ترند")

    for vid, title in videos:
        tags = smart_tag_selection(title, trends)
        if tags:
            update_video(yt, vid, title, tags)
            time.sleep(2) # عشان ما ننحظر
