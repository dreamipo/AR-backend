import os
import shutil
import time
from typing import List

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from utils.tripo_sdk_client import generate_3d_from_images
from utils.supabase_client import upload_to_supabase

app = FastAPI(title="Tripo3D Backend", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "./uploads"
OUTPUT_DIR = "./output"
OUTPUT_GLB = "./output/glb"
OUTPUT_USDZ = "./output/usdz"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_GLB, exist_ok=True)
os.makedirs(OUTPUT_USDZ, exist_ok=True)

app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")


@app.post("/generate-3d-model")
async def generate_3d_model(files: List[UploadFile] = File(...)):
    saved_files = []

    # Save uploaded images
    for f in files:
        save_path = os.path.join(UPLOAD_DIR, f.filename)
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(f.file, buffer)
        saved_files.append(save_path)

    print(f"📸 Received {len(saved_files)} images. Generating model...")

    # Generate GLB + USDZ
    result = await generate_3d_from_images(saved_files, formats=["glb", "usdz"])

    if result.get("status") != "success":
        return result

    bucket = os.getenv("SUPABASE_BUCKET")
    supabase_urls = {"glb": [], "usdz": [], "thumbnail": None}

    def upload(filepath: str, folder: str):
        filename = os.path.basename(filepath)
        dest = f"models/{folder}/{int(time.time())}_{filename}"
        return upload_to_supabase(filepath, dest, bucket)

    # ------------------------
    # 1️⃣ Upload GLB
    # ------------------------
    glb_local = result.get("pbr_model")

    if glb_local and os.path.exists(glb_local):
        new_glb_path = os.path.join(OUTPUT_GLB, os.path.basename(glb_local))
        shutil.move(glb_local, new_glb_path)
        glb_url = upload(new_glb_path, "glb")
        supabase_urls["glb"].append(glb_url)

    # ------------------------
    # 2️⃣ Upload USDZ
    # ------------------------
    for usdz in result.get("files", {}).get("usdz", []):
        new_usdz_path = os.path.join(OUTPUT_USDZ, os.path.basename(usdz))
        shutil.move(usdz, new_usdz_path)
        url = upload(new_usdz_path, "usdz")
        supabase_urls["usdz"].append(url)

    # ------------------------
    # 3️⃣ Upload thumbnail (first input image)
    # ------------------------
    if saved_files:
        print("⬆️ Uploading thumbnail...")
        first_image = saved_files[0]
        thumbnail_url = upload(first_image, "thumbnails")
        supabase_urls["thumbnail"] = thumbnail_url

    print("🚀 Upload complete:", supabase_urls)

    return {
        "status": "success",
        "message": "Models generated & uploaded",
        "file_urls": supabase_urls
    }


@app.get("/output/{filename}")
async def serve_model(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        return {"error": "Not found"}
    return FileResponse(file_path)
