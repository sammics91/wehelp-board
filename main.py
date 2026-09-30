from io import BytesIO
import os
from uuid import uuid4

import boto3
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
import mysql.connector
from PIL import Image, UnidentifiedImageError


app = FastAPI()

s3 = boto3.client("s3", region_name="ap-east-2")
S3_BUCKET = "sammics-board-images-2026"


def get_db_connection():
    return mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"]
    )


@app.get("/")
def index():
    return FileResponse("index.html")

# ----- GET /api/posts API -------------
@app.get("/api/posts")
def get_posts():
    connection = get_db_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        try:
            cursor.execute(
                "SELECT id, message, image_key, created_at FROM posts ORDER BY id DESC LIMIT 20"
            )
            posts = cursor.fetchall()
        finally:
            cursor.close()
    finally:
        connection.close()

    return {"posts": posts}


# ----- POST /api/posts API -------------
@app.post("/api/posts")
def create_post(
    message: str = Form(...),
    image: UploadFile = File(...)
):
    # 檢核留言文字內容
    message = message.strip()

    if message == "":
        raise HTTPException(status_code=400, detail="留言不能空白")

    if len(message) > 30:
        raise HTTPException(status_code=400, detail="留言最多只能有30個字")

    # 檢核圖片格式、大小
    allowed_types = {"image/jpeg", "image/png", "image/webp"}

    if image.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="圖片請使用 JPEG、PNG 或 WebP 格式")

    max_size = 5*1024*1024
    image_data = image.file.read(max_size + 1) #只讀取比最大限制多 1 byte

    if len(image_data) == 0:
        raise HTTPException(status_code=400, detail="圖片檔案不能是空的")

    if len(image_data) > max_size:
        raise HTTPException(status_code=413, detail="圖片大小不能超過 5 MiB")

    try:
        with Image.open(BytesIO(image_data)) as picture:
            if picture.format not in {"JPEG", "PNG", "WEBP"}:
                raise HTTPException(status_code=400, detail="圖片實際格式必須是 JPEG、PNG 或 WebP")

            extensions = {
                "JPEG": ".jpg",
                "PNG": ".png",
                "WEBP": ".webp"
            }

            extension = extensions[picture.format]

            content_types = {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
                "WEBP": "image/webp"
            }
            content_type = content_types[picture.format]

            picture.verify()

    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="圖片無法讀取或檔案已損壞")

    image.file.seek(0) #將檔案讀取位置移回「圖片檔案資料的開頭」

    object_key = f"images/{uuid4().hex}{extension}"

    s3.upload_fileobj(
        image.file,
        S3_BUCKET,
        object_key,
        ExtraArgs={"ContentType": content_type}
    )

    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        try:
            cursor.execute(
                "INSERT INTO posts (message, image_key) VALUES (%s, %s)",
                (message, object_key)
            )
            connection.commit()

        finally:
            cursor.close()
    finally:
        connection.close()

    return {
        "received_message": message,
        "filename": image.filename,
        "object_key": object_key
    }