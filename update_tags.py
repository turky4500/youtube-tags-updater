import os, base64, pickle, re, json, time
import urllib.request, urllib.parse, xml.etree.ElementTree as ET
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
MAX_VIDEOS_PER_RUN = 3
DAYS_BETWEEN_UPDATES = 30     # لا نعيد تعديل فيديو قبل 30 يوم
MIN_TAGS_TO_SKIP = 8          # نترك الفيديو إذا كانت وسومه كافية
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"
ADD_HASHTAGS = os.environ.get("ADD_HASHTAGS", "0") == "1"  # معطّل افتراضياً

LOG_FILE = 'update_log.json'
CHANGE_LOG_FILE = 'change_log.json'

ARABIC_CHARS = re.compile(r'[\u0600-\u06FF]')

# كلمات شائعة لا تضيف قيمة كوسوم
STOPWORDS = {
    'في', 'على', 'الى', 'إلى', 'من', 'عن', 'ان', 'أن', 'إن', 'هذا', 'هذه',
    'ذلك', 'التي', 'الذي', 'ما', 'لا', 'لم', 'لن', 'هو', 'هي', 'كل', 'كان',
    'كانت', 'مع', 'عند', 'بعد', 'قبل', 'حتى', 'اذا', 'إذا', 'ثم', 'او', 'أو',
    'يا', 'فيه', 'فيها', 'عليه', 'عليها', 'وال', 'عربي', 'يوتيوب', 'فيديو',
    'مقطع', 'مقاطع', 'قناة', 'اشترك', 'لايك', 'شكرا', 'جديد', 'اليوم', 'طريقة',
    'أفضل', 'افضل', 'شرح', 'كيف', 'ما', 'سو', 'و'
}

# كلمات نستبعدها من الترندات (أخبار/رياضة لا تصلح كوسوم لمحتوى عام)
BANNED_WORDS = [
    'vs', 'espanyol', 'levante', 'lazio', 'udinese', 'fc', 'match', 'game',
    'champions', 'league', 'مباراة', 'نادي', 'هداف', 'دوري', 'بث مباشر',
    'أخبار', 'عاجل', 'وفاة', 'توفي', 'حادث'
]


def get_authenticated_service():
    token_bytes = base64.b64decode(TOKEN_PICKLE_B64)
    credentials = pickle.loads(token_bytes)
    if credentials.expired and credentials.refresh_token:
        print("🔄 تجديد الجلسة...")
        credentials.refresh(Request())
    return build('youtube', 'v3', credentials=credentials)


def extract_keywords(text, min_len=3):
    """استخراج الكلمات المهمة (عربية/إنجليزية) مع استبعاد الكلمات الشائعة."""
    if not text:
        return []
    words = re.findall(r'[a-zA-Z]{3,}|[\u0600-\u06FF]{3,}', text.lower())
    return [w for w in words if w not in STOPWORDS]


def youtube_autocomplete(query):
    """اقتراحات يوتيوب الحقيقية = ما يبحث عنه الناس فعلاً حول الموضوع."""
    url = (
        "https://suggestqueries.google.com/complete/search"
        "?client=firefox&ds=yt&hl=ar&gl=SA&q=" + urllib.parse.quote(query)
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode('utf-8'))
    return data[1] if len(data) > 1 else []


def get_trending_keywords():
    """ترند السعودية — يُستخدم فقط كمرشح إضافي (لا يُضاف عشوائياً)."""
    try:
        rss_url = "https://trends.google.com/trending/rss?geo=SA"
        with urllib.request.urlopen(rss_url, timeout=10) as response:
            rss_data = response.read().decode('utf-8')
        root = ET.fromstring(rss_data)
        keywords = []
        for item in root.findall('.//item'):
            title_elem = item.find('title')
            title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
            if title and ARABIC_CHARS.search(title):
                if not any(bad in title.lower() for bad in BANNED_WORDS):
                    keywords.append(title)
        return list(dict.fromkeys(keywords))[:20]
    except Exception as e:
        print(f"⚠️ خطأ بالترند: {e}")
        return []


def word_overlap(candidate, topic_words):
    """هل يشترك النص المرشح بكلمة مع كلمات موضوع الفيديو؟"""
    return bool(set(extract_keywords(candidate)) & topic_words)


def normalize_tag(t):
    t = (t or '').strip().strip('#').strip()
    t = re.sub(r'\s+', ' ', t)
    if len(t) > 30:
        t = t[:30].rstrip()
    return t


def build_tags(youtube, title, description, existing_tags):
    """
    بناء الوسوم بالترتيب حسب الأولوية — كل شيء مرتبط بموضوع الفيديو فقط:
    1) كلمات العنوان
    2) اقتراحات بحث يوتيوب ذات الصلة
    3) ترندات ذات صلة (تشترك بكلمة مع الموضوع)
    4) الوسوم القديمة (نحتفظ بها)
    لا نضيف أي وسم عشوائي غير ذي صلة إطلاقاً.
    """
    topic_words = set(extract_keywords(title + " " + description))
    existing = [normalize_tag(t) for t in existing_tags]

    # 1) كلمات العنوان
    title_kws = extract_keywords(title)[:5]

    # 2) اقتراحات يوتيوب حول أول كلمتين مهمتين من العنوان
    suggestions = []
    for seed in extract_keywords(title)[:2]:
        try:
            suggestions += youtube_autocomplete(seed)
        except Exception:
            pass
    relevant_suggestions = [s for s in suggestions if word_overlap(s, topic_words)]

    # 3) ترندات ذات صلة فقط
    trends = get_trending_keywords()
    relevant_trends = [t for t in trends if word_overlap(t, topic_words)]

    # 4) الدمج حسب الأولوية
    final, seen = [], set()
    for tag in title_kws + relevant_suggestions + relevant_trends + existing:
        t = normalize_tag(tag)
        if not t or t in seen:
            continue
        seen.add(t)
        final.append(t)

    # حد أقصى لعدد الوسوم + 500 حرف إجمالي
    total, out = 0, []
    for t in final[:MAX_TAGS_PER_VIDEO]:
        if total + len(t) + 1 > 500:
            break
        out.append(t)
        total += len(t) + 1
    return out


def get_videos_to_update(youtube, update_log):
    """نختار الفيديوهات التي تحتاج تحسين وسوم فعلاً (الجديدة أو قليلة الوسوم)."""
    req = youtube.channels().list(part="contentDetails", mine=True)
    uploads_id = req.execute()['items'][0]['contentDetails']['relatedPlaylists']['uploads']

    items, page_token = [], None
    while True:
        r = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=50, pageToken=page_token
        ).execute()
        for it in r['items']:
            items.append({
                'vid': it['snippet']['resourceId']['videoId'],
                'title': it['snippet']['title'],
                'published': it['snippet']['publishedAt'],
            })
        page_token = r.get('nextPageToken')
        if not page_token:
            break

    # جلب الوسوم والوصف الحالي دفعة واحدة (توفير للكوتا)
    vids = [x['vid'] for x in items]
    meta = {}
    for i in range(0, len(vids), 50):
        batch = vids[i:i + 50]
        r = youtube.videos().list(part="snippet", id=",".join(batch)).execute()
        for it in r.get('items', []):
            meta[it['id']] = {
                'tags': it['snippet'].get('tags', []),
                'description': it['snippet'].get('description', ''),
            }

    today = datetime.now()
    cutoff = today - timedelta(days=DAYS_BETWEEN_UPDATES)
    candidates = []
    for it in items:
        vid = it['vid']
        lu = update_log.get(vid)
        if lu:
            try:
                if datetime.fromisoformat(lu) > cutoff:
                    continue  # حُدّث مؤخراً
            except Exception:
                pass
        m = meta.get(vid, {})
        tags = m.get('tags', [])
        if len(tags) >= MIN_TAGS_TO_SKIP:
            continue  # الوسوم كافية، نتركه
        candidates.append({
            'vid': vid,
            'title': it['title'],
            'tags': tags,
            'description': m.get('description', ''),
            'published_dt': datetime.fromisoformat(it['published'].replace('Z', '+00:00')),
        })

    candidates.sort(key=lambda x: x['published_dt'], reverse=True)  # الأحدث أولاً
    return candidates[:MAX_VIDEOS_PER_RUN]


def update_video(youtube, video_id, title, new_tags):
    try:
        req = youtube.videos().list(part="snippet", id=video_id)
        res = req.execute()
        if not res['items']:
            return False, "الفيديو غير موجود", None
        snippet = res['items'][0]['snippet']
        old_tags = snippet.get('tags', [])
        snippet['tags'] = new_tags

        if ADD_HASHTAGS and new_tags:
            hashtags = " ".join(f"#{t.replace(' ', '_')}" for t in new_tags[:3])
            old_desc = snippet.get('description', '')
            lines = old_desc.split('\n')
            if lines and lines[0].lstrip().startswith('#'):
                old_desc = '\n'.join(lines[1:]).lstrip('\n')
            snippet['description'] = f"{hashtags}\n\n{old_desc}"

        youtube.videos().update(
            part="snippet", body={"id": video_id, "snippet": snippet}
        ).execute()
        return True, f"✅ {title[:35]} | {len(old_tags)} → {len(new_tags)} وسماً", (old_tags, new_tags)
    except HttpError as e:
        return False, f"❌ خطأ: {e}", None


def load_json(path):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mode = "🧪 DRY-RUN" if DRY_RUN else "🚀 LIVE"
    print(f"{mode} — تحديث الوسوم الذكي v2")
    yt = get_authenticated_service()
    update_log = load_json(LOG_FILE)
    change_log = load_json(CHANGE_LOG_FILE)

    videos = get_videos_to_update(yt, update_log)
    print(f"🔍 {len(videos)} فيديو يحتاج تحسين وسوم")

    if not videos:
        print("✅ لا شيء يحتاج تحديثاً — الوسوم سليمة")
    for v in videos:
        vid, title = v['vid'], v['title']
        new_tags = build_tags(yt, title, v['description'], v['tags'])

        if DRY_RUN:
            print(f"🧪 [DRY] {title[:40]}")
            print(f"      {' | '.join(new_tags[:6])}")
            continue

        success, msg, change = update_video(yt, vid, title, new_tags)
        print(msg)
        update_log[vid] = datetime.now().isoformat()
        if change:
            change_log[vid] = {
                "title": title,
                "old_tags": change[0],
                "new_tags": change[1],
                "updated_at": datetime.now().isoformat(),
            }
        save_json(LOG_FILE, update_log)
        save_json(CHANGE_LOG_FILE, change_log)
        time.sleep(3)

    print("🎉 انتهى التشغيل")
