import os
import base64
import pickle

from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_PICKLE_B64 = os.environ.get("TOKEN_PICKLE_B64")


def main():
    if not TOKEN_PICKLE_B64:
        raise RuntimeError("السر TOKEN_PICKLE_B64 غير موجود")
    token_bytes = base64.b64decode(TOKEN_PICKLE_B64)
    credentials = pickle.loads(token_bytes)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    youtube = build("youtube", "v3", credentials=credentials)

    ch = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    items, page_token = [], None
    while True:
        resp = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id, maxResults=50, pageToken=page_token
        ).execute()
        for it in resp.get("items", []):
            sn = it["snippet"]
            items.append((sn["resourceId"]["videoId"], sn["title"], sn["publishedAt"][:10]))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    print(f"TOTAL_VIDEOS={len(items)}")
    for vid, title, pub in items:
        print(f"{vid} | {title} | {pub}")


if __name__ == "__main__":
    main()
