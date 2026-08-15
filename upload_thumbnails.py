import os
import base64
import pickle

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

CLIENT_SECRET_JSON_B64 = os.environ.get("CLIENT_SECRET_JSON_B64")
TOKEN_PICKLE_B64 = os.environ.get("TOKEN_PICKLE_B64")

# الخريطة: مسار الصورة -> معرّف الفيديو
THUMBNAILS = {
    "thumbnails/thumb_accidents.jpg": "1b-u119j_Wc",
    "thumbnails/thumb_traffic.jpg": "HZZNEtJ74aw",
    "thumbnails/thumb_kashta_thursday.jpg": "sYqvqHCd4wQ",
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


def main():
    youtube = get_authenticated_service()
    for path, video_id in THUMBNAILS.items():
        if not os.path.exists(path):
            print(f"⚠️ الملف غير موجود: {path}")
            continue
        print(f"⬆️ رفع مصغرة «{path}» للفيديو {video_id} ...")
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(path, mimetype="image/jpeg", resumable=True),
        ).execute()
        print(f"✅ تم رفع مصغرة الفيديو {video_id}")
    print("🎉 انتهى رفع المصغرات")


if __name__ == "__main__":
    main()
