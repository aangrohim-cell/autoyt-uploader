import os
import io
import json
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

# ===== CONFIG =====
DRIVE_FOLDER_NAME = "AutoUploadYT"
VIDEOS_FOLDER = "videos"
DONE_FOLDER = "done"

# ===== LOAD SERVICE ACCOUNT FROM SECRET =====
gdrive_json = os.environ.get("GDRIVE_JSON")
if not gdrive_json:
    raise Exception("GDRIVE_JSON secret not found")

creds_info = json.loads(gdrive_json)
creds = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/drive"]
)

drive_service = build("drive", "v3", credentials=creds)

# ===== HELPER =====
def find_folder(name, parent_id=None):
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    res = drive_service.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None

# ===== FIND FOLDERS =====
root_id = find_folder(DRIVE_FOLDER_NAME)
if not root_id:
    raise Exception("Folder AutoUploadYT not found")

videos_id = find_folder(VIDEOS_FOLDER, root_id)
done_id = find_folder(DONE_FOLDER, root_id)

if not videos_id or not done_id:
    raise Exception("videos/done folder not found")

# ===== LIST FILES =====
res = drive_service.files().list(
    q=f"'{videos_id}' in parents and trashed=false",
    fields="files(id,name,size)"
).execute()

files = res.get("files", [])

if not files:
    print("No files to upload.")
    exit(0)

# ===== PROCESS ONE VIDEO =====
video_file = None
for f in files:
    if f["name"].lower().endswith(".mp4"):
        video_file = f
        break

if not video_file:
    print("No mp4 found.")
    exit(0)

base = os.path.splitext(video_file["name"])[0]

def find_by_name(name):
    res = drive_service.files().list(
        q=f"'{videos_id}' in parents and name='{name}' and trashed=false",
        fields="files(id,name)"
    ).execute()
    fs = res.get("files", [])
    return fs[0] if fs else None

txt = find_by_name(base + ".txt")
jpg = find_by_name(base + ".jpg")

if not txt:
    print("TXT not found, skip.")
    exit(0)

# ===== DOWNLOAD FILES =====
def download(file_id, filename):
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.FileIO(filename, "wb")
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()

download(video_file["id"], "video.mp4")
download(txt["id"], "desc.txt")
if jpg:
    download(jpg["id"], "thumb.jpg")

# ===== READ DESCRIPTION =====
with open("desc.txt", "r", encoding="utf-8") as f:
    content = f.read().splitlines()

title = content[0]
description = "\n".join(content[1:])

# ===== YOUTUBE UPLOAD =====
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_console()

youtube = build("youtube", "v3", credentials=creds)

body = {
    "snippet": {
        "title": title,
        "description": description,
        "categoryId": "10"
    },
    "status": {
        "privacyStatus": "public"
    }
}

media = MediaFileUpload("video.mp4", chunksize=1024*1024*8, resumable=True)

request = youtube.videos().insert(
    part="snippet,status",
    body=body,
    media_body=media
)

response = None
while response is None:
    status, response = request.next_chunk()
    if status:
        print(f"Upload {int(status.progress()*100)}%")

print("UPLOAD DONE:", response["id"])

# ===== MOVE FILES TO DONE =====
def move(file):
    drive_service.files().update(
        fileId=file["id"],
        addParents=done_id,
        removeParents=videos_id
    ).execute()

move(video_file)
move(txt)
if jpg:
    move(jpg)

print("Moved to done folder.")
