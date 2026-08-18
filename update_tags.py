import os, base64, pickle, re, json, time
import urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ============ الإعدادات ============
CLIENT_SECRET_JSON_B64 = os.environ.get("CLIENT_SECRET_JSON_B64")
TOKEN_PICKLE_B64 = os.environ.get("TOKEN_PICKLE_B64")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

MAX_TAGS_PER_VIDEO = 12
MAX_VIDEOS_PER_RUN = 3
HASHTAGS_PER_VIDEO = 5
MAX_HASHTAG_LEN = 30
DAYS_BETWEEN_UPDATES = 30
OPTIMIZER_VERSION = 7
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

LOG_FILE = "update_log.json"
CHANGE_LOG_FILE = "change_log.json"
DESCRIPTION_CTA = "إذا أعجبك الفيديو، شاركنا رأيك في التعليقات واشترك في القناة لمتابعة المزيد."

STOPWORDS = {
    "في", "على", "الى", "إلى", "من", "عن", "ان", "أن", "إن", "هذا", "هذه",
    "ذلك", "التي", "الذي", "ما", "لا", "لم", "لن", "هو", "هي", "كل", "كان",
    "كانت", "مع", "عند", "بعد", "قبل", "حتى", "اذا", "إذا", "ثم", "او", "أو",
    "يا", "فيه", "فيها", "عليه", "عليها", "وال", "يوتيوب", "فيديو", "مقطع",
    "مقاطع", "قناة", "اشترك", "لايك", "شكرا", "اليوم", "و"
}

BANNED_WORDS = {
    "vs", "espanyol", "levante", "lazio", "udinese", "fc", "match", "game",
    "champions", "league", "مباراة", "نادي", "هداف", "دوري", "بث مباشر",
    "أخبار", "عاجل", "وفاة", "توفي", "حادث"
}


def get_authenticated_service():
    if not TOKEN_PICKLE_B64:
        raise RuntimeError("السر TOKEN_PICKLE_B64 غير موجود")
    try:
        token_bytes = base64.b64decode(TOKEN_PICKLE_B64)
        credentials = pickle.loads(token_bytes)
    except Exception as e:
        raise RuntimeError("تعذّر قراءة بيانات اعتماد يوتيوب") from e

    if credentials.expired and credentials.refresh_token:
        print("🔄 تجديد جلسة يوتيوب...")
        credentials.refresh(Request())
    return build("youtube", "v3", credentials=credentials)


def normalize_for_match(text):
    """توحيد بسيط للحروف العربية حتى تكون مقارنة الكلمات أدق."""
    text = (text or "").lower()
    text = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", text)
    return text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي"}))


def extract_keywords(text):
    if not text:
        return []
    words = re.findall(r"[a-zA-Z]{3,}|[\u0600-\u06FF]{2,}", text)
    normalized_stopwords = {normalize_for_match(w) for w in STOPWORDS}
    result = []
    for word in words:
        normalized = normalize_for_match(word)
        if normalized and normalized not in normalized_stopwords:
            result.append(word.strip())
    return result


def keyword_set(text):
    return {normalize_for_match(w) for w in extract_keywords(text)}


def contains_banned_words(text):
    normalized = normalize_for_match(text)
    return any(normalize_for_match(word) in normalized for word in BANNED_WORDS)


def youtube_autocomplete(query):
    """اقتراحات بحث يوتيوب الفعلية للسعودية."""
    url = (
        "https://suggestqueries.google.com/complete/search"
        "?client=firefox&ds=yt&hl=ar&gl=SA&q=" + urllib.parse.quote(query)
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data[1] if len(data) > 1 and isinstance(data[1], list) else []


def normalize_tag(tag):
    tag = re.sub(r"#+", " ", tag or "")
    tag = re.sub(r"\s+", " ", tag).strip(" #")
    if not tag or len(tag) > 100 or contains_banned_words(tag):
        return ""
    return tag


def clean_title_for_text(title):
    """إزالة رموز # و _ من العنوان مع الإبقاء على الكلمات، وإزالة تكرار الكلمات."""
    text = re.sub(r"[#_]", " ", title or "")
    words, seen = [], set()
    for word in re.split(r"\s+", text.strip()):
        if not word:
            continue
        key = normalize_for_match(word)
        if key in seen:
            continue
        seen.add(key)
        words.append(word)
    return " ".join(words)


def tag_is_relevant(tag, title_words):
    """علامة من كلمة تحتاج تطابق كلمة في العنوان، ومن كلمتين+ تحتاج كلمتين على الأقل."""
    tag_words = keyword_set(tag)
    if not tag_words or not title_words:
        return False
    overlap = tag_words & title_words
    if len(tag_words) == 1:
        return len(overlap) >= 1
    return len(overlap) >= 2


def suggestion_is_relevant(suggestion, title):
    title_words = keyword_set(title)
    suggestion_words = keyword_set(suggestion)
    if not title_words or not suggestion_words or contains_banned_words(suggestion):
        return False
    overlap = title_words & suggestion_words
    required = 1 if len(title_words) == 1 else 2
    return len(overlap) >= min(required, len(title_words))


def get_relevant_suggestions(title):
    """نجلب اقتراحات لعبارة العنوان، ولا نستخدم اقتراحات كلمة عامة منفردة."""
    queries = [title.strip()]
    title_keywords = extract_keywords(title)
    if len(title_keywords) > 4:
        queries.append(" ".join(title_keywords[:4]))
    if len(title_keywords) == 1:
        queries.append(title_keywords[0])

    suggestions = []
    for query in dict.fromkeys(q for q in queries if q):
        try:
            suggestions.extend(youtube_autocomplete(query))
        except Exception as e:
            print(f"⚠️ تعذّر جلب اقتراحات «{query[:30]}»: {e}")

    return [s for s in dict.fromkeys(suggestions) if suggestion_is_relevant(s, title)]


def build_tags(title, description, existing_tags):
    """بناء علامات مرتبطة مباشرة بالعنوان والمحتوى، دون حشو عشوائي."""
    cleaned_title = clean_title_for_text(title)
    title_phrase = normalize_tag(cleaned_title)
    title_keywords = [normalize_tag(w) for w in extract_keywords(cleaned_title)]
    suggestions = [normalize_tag(s) for s in get_relevant_suggestions(cleaned_title)]

    title_words = keyword_set(cleaned_title)
    relevant_existing = []
    for tag in existing_tags or []:
        cleaned = normalize_tag(tag)
        if cleaned and tag_is_relevant(cleaned, title_words):
            relevant_existing.append(cleaned)

    final, seen = [], set()
    for tag in [title_phrase] + suggestions + title_keywords + relevant_existing:
        if not tag:
            continue
        key = normalize_for_match(tag)
        if key in seen:
            continue
        seen.add(key)
        final.append(tag)

    output, total = [], 0
    for tag in final:
        extra = len(tag) + (1 if output else 0)
        if len(output) >= MAX_TAGS_PER_VIDEO or total + extra > 500:
            break
        output.append(tag)
        total += extra
    return output


def hashtag_value(text):
    text = normalize_tag(text)
    if not text:
        return ""
    text = re.sub(r"[^a-zA-Z0-9_\u0600-\u06FF\s]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    if not text or len(text) > MAX_HASHTAG_LEN:
        return ""
    return "#" + text


def build_hashtags(title, tags):
    cleaned_title = clean_title_for_text(title)
    candidates = [cleaned_title] + extract_keywords(cleaned_title) + list(tags)
    hashtags, seen = [], set()
    for candidate in candidates:
        hashtag = hashtag_value(candidate)
        key = normalize_for_match(hashtag)
        if not hashtag or key in seen:
            continue
        seen.add(key)
        hashtags.append(hashtag)
        if len(hashtags) >= HASHTAGS_PER_VIDEO:
            break
    return hashtags


def is_hashtag_line(line):
    parts = line.strip().split()
    return bool(parts) and all(part.startswith("#") for part in parts)


def clean_existing_description(description, title):
    """إزالة إضافات السكربت السابقة مع الحفاظ على أي معلومات أصلية مفيدة."""
    text = (description or "").replace("\r\n", "\n").strip()
    if not text:
        return ""

    # إزالة الجزء الآلي الذي أضافته هذه النسخة في تشغيل سابق.
    if DESCRIPTION_CTA in text:
        text = text.split(DESCRIPTION_CTA, 1)[0].rstrip()

    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)

    # إزالة العنوان الذي وضعه السكربت في أول الوصف سابقاً.
    if lines and normalize_for_match(lines[0].strip()) == normalize_for_match(title.strip()):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)

    # إزالة سطر الهاشتاقات القديم من النسخة السابقة بأمان.
    if lines and lines[0].lstrip().startswith("#"):
        if "تحديث" in lines[0] or is_hashtag_line(lines[0]):
            lines.pop(0)
            while lines and not lines[0].strip():
                lines.pop(0)

    # إزالة أسطر الهاشتاقات القديمة الموجودة في نهاية الوصف.
    while lines and (not lines[-1].strip() or is_hashtag_line(lines[-1])):
        lines.pop()

    return "\n".join(lines).strip()


def ai_description(title, existing_description):
    """توليد وصف قصير بالذكاء الاصطناعي عبر Google Gemini.

    يرجع None عندما لا يتوفر المفتاح أو يفشل الاتصال، حتى لا يتعطل التشغيل.
    """
    if not GEMINI_API_KEY:
        return None

    hint = (existing_description or "").strip()
    if len(hint) > 400:
        hint = hint[:400] + "…"

    prompt = (
        "اكتب وصفاً قصيراً وجذاباً لفيديو يوتيوب عنوانه: «{title}».\n"
        "المطلوب:\n"
        "- جملتان إلى ثلاث جمل بالعربية الفصحى المبسطة والطبيعية.\n"
        "- اشرح ما يقدمه الفيديو بصورة عامة وواضحة دون اختراع تفاصيل أو أسماء غير مذكورة.\n"
        "- لا تستخدم هاشتاقات ولا رموز تعبيرية (إيموجي).\n"
        "- لا تذكر أرقاماً أو وعوداً غير مؤكدة.\n"
        "أعد نص الوصف فقط دون أي مقدمة أو خاتمة أو شرح."
    ).format(title=title)

    if hint:
        prompt += "\nالوصف الحالي للفيديو (استفد منه إن كان مفيداً): " + hint

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 350},
    }).encode("utf-8")

    for model in ["gemini-flash-lite-latest", "gemini-3.6-flash", "gemini-3.7-flash"]:
        try:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                + model + ":generateContent?key=" + urllib.parse.quote(GEMINI_API_KEY)
            )
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            candidates = data.get("candidates") or []
            if not candidates:
                continue
            parts = candidates[0].get("content", {}).get("parts") or []
            text = "".join(
                part.get("text", "") for part in parts if not part.get("thought", False)
            ).strip()
            if text and _looks_like_description(text):
                return text
        except Exception as e:
            print(f"⚠️ تعذّر توليد الوصف الذكي عبر {model}: {e}")

    return None


def _looks_like_description(text):
    """فحص بسيط يرفض الردود غير الطبيعية (إنجليزية زائدة أو نص بنيوي من النموذج)."""
    if not text or len(text) < 8:
        return False
    low = text.lower()
    if any(word in low for word in ["call to action", "wrap up", "hashtag", "emoji", "```"]):
        return False
    latin = len(re.findall(r"[a-zA-Z]", text))
    arabic = len(re.findall(r"[\u0600-\u06FF]", text))
    if arabic == 0 or latin > arabic:
        return False
    return True


def build_description_smart(title, existing_description, hashtags):
    """بناء الوصف كاملاً للمرة الأولى: يحاول توليد وصف ذكي، ويرجع للوصف العادي عند الفشل.

    يرجع زوجاً: (الوصف الكامل, هل استُخدم الذكاء الاصطناعي فعلاً).
    """
    clean_title = clean_title_for_text(title) or title.strip()
    cleaned_body = clean_existing_description(existing_description, title)
    ai_body = ai_description(clean_title, cleaned_body)
    ai_used = bool(ai_body)
    body = ai_body if ai_body else cleaned_body
    if not body:
        body = f"فيديو بعنوان «{clean_title}» يقدم محتوى مرتبطًا بموضوع الفيديو بصورة واضحة ومباشرة."

    hashtag_line = " ".join(hashtags)
    fixed_parts = [clean_title, DESCRIPTION_CTA, hashtag_line]
    fixed_length = sum(len(part) for part in fixed_parts) + 4
    max_body_length = max(0, 5000 - fixed_length)
    if len(body) > max_body_length:
        body = body[:max_body_length].rsplit("\n", 1)[0].rstrip() or body[:max_body_length].rstrip()

    return "\n\n".join(part for part in [clean_title, body, DESCRIPTION_CTA, hashtag_line] if part), ai_used


def refresh_hashtags_only(description, hashtags):
    """تحديث سطر الهاشتاقات فقط مع الحفاظ على باقي الوصف (الوضع الدائم بعد المرة الأولى).

    يرجع None إذا كان الوصف فارغاً أو ناقصاً حتى يبنى وصف كامل بدلاً من سطر وحيد.
    """
    text = (description or "").replace("\r\n", "\n").strip()
    lines = text.split("\n")
    while lines and (not lines[-1].strip() or is_hashtag_line(lines[-1])):
        lines.pop()
    body = "\n".join(lines).strip()
    if not body:
        return None
    return body + "\n\n" + " ".join(hashtags)


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ملف السجل {path} تالف؛ أوقفنا التشغيل لحماية البيانات") from e


def save_json(path, data):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def get_videos_to_update(youtube, change_log):
    """اختيار 3 فيديوهات يومياً، مع المرور على جميع فيديوهات القناة."""
    channel_response = youtube.channels().list(part="contentDetails", mine=True).execute()
    if not channel_response.get("items"):
        raise RuntimeError("لم نجد قناة يوتيوب مرتبطة ببيانات الاعتماد")
    uploads_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    items, page_token = [], None
    while True:
        response = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=50, pageToken=page_token
        ).execute()
        for item in response.get("items", []):
            snippet = item["snippet"]
            items.append({
                "vid": snippet["resourceId"]["videoId"],
                "title": snippet["title"],
                "published": snippet["publishedAt"],
            })
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    video_ids = [item["vid"] for item in items]
    metadata = {}
    for index in range(0, len(video_ids), 50):
        batch = video_ids[index:index + 50]
        response = youtube.videos().list(part="snippet", id=",".join(batch)).execute()
        for item in response.get("items", []):
            snippet = item["snippet"]
            metadata[item["id"]] = {
                "tags": snippet.get("tags", []),
                "description": snippet.get("description", ""),
            }

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=DAYS_BETWEEN_UPDATES)
    candidates = []
    for item in items:
        meta = metadata.get(item["vid"])
        if meta is None:
            continue

        record = change_log.get(item["vid"], {})
        version = record.get("optimizer_version", 0) if isinstance(record, dict) else 0
        last_updated = parse_datetime(record.get("last_updated_at")) if isinstance(record, dict) else None
        already_current = version >= OPTIMIZER_VERSION
        if already_current and last_updated and last_updated > cutoff:
            continue

        candidates.append({
            **item,
            **meta,
            "published_dt": parse_datetime(item["published"]) or datetime.min.replace(tzinfo=timezone.utc),
            "optimizer_version": version,
            "last_optimized_dt": last_updated,
        })

    # غير المعالجة بهذه النسخة أولاً (الأحدث نشراً)، ثم الأقدم تحسيناً.
    candidates.sort(
        key=lambda item: (
            0 if item["optimizer_version"] < OPTIMIZER_VERSION else 1,
            -item["published_dt"].timestamp()
            if item["optimizer_version"] < OPTIMIZER_VERSION
            else (item["last_optimized_dt"] or datetime.min.replace(tzinfo=timezone.utc)).timestamp(),
        )
    )
    return candidates[:MAX_VIDEOS_PER_RUN]


def update_video(youtube, video_id, title, new_tags, new_description):
    try:
        response = youtube.videos().list(part="snippet", id=video_id).execute()
        if not response.get("items"):
            return False, "الفيديو غير موجود", None

        snippet = response["items"][0]["snippet"]
        old_tags = list(snippet.get("tags", []))
        old_description = snippet.get("description", "")
        changed = old_tags != new_tags or old_description != new_description

        if changed:
            snippet["tags"] = new_tags
            snippet["description"] = new_description
            youtube.videos().update(
                part="snippet", body={"id": video_id, "snippet": snippet}
            ).execute()

        change = {
            "old_tags": old_tags,
            "new_tags": new_tags,
            "description_changed": old_description != new_description,
        }
        status = "تم التحسين" if changed else "لا يحتاج تغييراً"
        counts = f"العلامات: قبل {len(old_tags)} / بعد {len(new_tags)}"
        return True, f"✅ {title[:35]} | {counts} | {status}", change
    except HttpError as e:
        return False, f"❌ خطأ YouTube API: {e}", None
    except Exception as e:
        return False, f"❌ خطأ غير متوقع: {e}", None


def record_change(change_log, video, change, hashtags, updated_at, ai_written=False):
    old_record = change_log.get(video["vid"], {})
    history = []
    if isinstance(old_record, dict):
        history = list(old_record.get("history", []))
        if not history and old_record.get("updated_at"):
            history.append({
                "old_tags": old_record.get("old_tags", []),
                "new_tags": old_record.get("new_tags", []),
                "updated_at": old_record.get("updated_at"),
                "optimizer_version": 2,
            })

    history.append({
        **change,
        "hashtags": hashtags,
        "updated_at": updated_at,
        "optimizer_version": OPTIMIZER_VERSION,
    })
    record = {
        "title": video["title"],
        "optimizer_version": OPTIMIZER_VERSION,
        "last_updated_at": updated_at,
        "history": history[-5:],
    }
    # الحفاظ على علم "الوصف الذكي كُتب" حتى لا يُعاد كتابة الوصف لاحقاً.
    if ai_written or (isinstance(old_record, dict) and old_record.get("ai_description_written")):
        record["ai_description_written"] = True
    change_log[video["vid"]] = record


if __name__ == "__main__":
    mode = "🧪 DRY-RUN" if DRY_RUN else "🚀 LIVE"
    print(f"{mode} — التحسين الشامل v{OPTIMIZER_VERSION} (علامات + وصف ذكي لمرة واحدة + هاشتاقات)")

    youtube = get_authenticated_service()
    update_log = load_json(LOG_FILE)
    change_log = load_json(CHANGE_LOG_FILE)
    videos = get_videos_to_update(youtube, change_log)
    print(f"🔍 وجدنا {len(videos)} فيديو للتحسين اليوم")

    if not videos:
        print("✅ لا يوجد فيديو يحتاج تحسيناً الآن")

    for video in videos:
        tags = build_tags(video["title"], video["description"], video["tags"])
        hashtags = build_hashtags(video["title"], tags)

        record = change_log.get(video["vid"], {})
        ai_written_before = isinstance(record, dict) and record.get("ai_description_written") is True

        if ai_written_before:
            # الوصف كُتب سابقاً: نحدّث سطر الهاشتاقات فقط ونبقي الوصف ثابتاً.
            description = refresh_hashtags_only(video["description"], hashtags)
            ai_used = False
            if description is None:
                description, ai_used = build_description_smart(video["title"], video["description"], hashtags)
        else:
            # المرة الأولى: بناء وصف كامل (يحاول توليد وصف ذكي).
            description, ai_used = build_description_smart(video["title"], video["description"], hashtags)

        if DRY_RUN:
            print(f"🧪 {video['title'][:45]}")
            print(f"   العلامات: {' | '.join(tags)}")
            print(f"   الهاشتاقات: {' '.join(hashtags)}")
            print(f"   الوصف الذكي: {'نعم' if ai_used else 'لا'}")
            continue

        success, message, change = update_video(
            youtube, video["vid"], video["title"], tags, description
        )
        print(message)
        if success and change:
            updated_at = datetime.now(timezone.utc).isoformat()
            update_log[video["vid"]] = updated_at
            record_change(change_log, video, change, hashtags, updated_at, ai_written=ai_used)
            save_json(LOG_FILE, update_log)
            save_json(CHANGE_LOG_FILE, change_log)
        time.sleep(3)

    print("🎉 انتهى التشغيل")
