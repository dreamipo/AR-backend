import os
import shutil
import time
import asyncio
from typing import List, Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from utils.supabase_client import upload_to_supabase

# Track active generation tasks
active_tasks: Dict[str, asyncio.Task] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown: cancel all active tasks
    for task_id, task in list(active_tasks.items()):
        if not task.done():
            task.cancel()
    active_tasks.clear()

app = FastAPI(title="Tripo3D Backend", version="1.3.0", lifespan=lifespan)

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

# Import after active_tasks is defined
from utils.tripo_sdk_client import generate_3d_from_images


async def process_3d_generation(saved_files: List[str], task_id: str):
    """Background task for 3D generation that can be cancelled"""
    try:
        print(f"📸 Processing task {task_id}: {len(saved_files)} images")
        
        # Check for cancellation before starting
        if task_id not in active_tasks:
            print(f"❌ Task {task_id} cancelled before generation started")
            # Cleanup uploaded files
            for f in saved_files:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception as e:
                        print(f"Failed to remove {f}: {e}")
            return {"status": "cancelled", "message": "Task was cancelled"}
        
        # Generate GLB + USDZ (pass task_id for cancellation checks)
        result = await generate_3d_from_images(
            saved_files, 
            formats=["glb", "usdz"],
            task_id=task_id
        )

        if result.get("status") == "cancelled":
            print(f"❌ Task {task_id} was cancelled during generation")
            # Cleanup uploaded files
            for f in saved_files:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception as e:
                        print(f"Failed to remove {f}: {e}")
            return result
            
        if result.get("status") != "success":
            return result

        # Check cancellation before uploads
        if task_id not in active_tasks:
            print(f"❌ Task {task_id} cancelled before upload")
            return {"status": "cancelled", "message": "Task was cancelled"}

        bucket = os.getenv("SUPABASE_BUCKET")
        supabase_urls = {"glb": [], "usdz": [], "thumbnail": None}

        def upload(filepath: str, folder: str):
            filename = os.path.basename(filepath)
            dest = f"models/{folder}/{int(time.time())}_{filename}"
            return upload_to_supabase(filepath, dest, bucket)

        # Upload GLB
        glb_local = result.get("pbr_model")
        if glb_local and os.path.exists(glb_local):
            new_glb_path = os.path.join(OUTPUT_GLB, os.path.basename(glb_local))
            shutil.move(glb_local, new_glb_path)
            glb_url = upload(new_glb_path, "glb")
            supabase_urls["glb"].append(glb_url)

        # Upload USDZ
        for usdz in result.get("files", {}).get("usdz", []):
            if task_id not in active_tasks:
                print(f"❌ Task {task_id} cancelled during USDZ upload")
                return {"status": "cancelled", "message": "Task was cancelled"}
            
            new_usdz_path = os.path.join(OUTPUT_USDZ, os.path.basename(usdz))
            shutil.move(usdz, new_usdz_path)
            url = upload(new_usdz_path, "usdz")
            supabase_urls["usdz"].append(url)

        # Upload thumbnail
        if saved_files:
            print("⬆️ Uploading thumbnail...")
            first_image = saved_files[0]
            if os.path.exists(first_image):
                thumbnail_url = upload(first_image, "thumbnails")
                supabase_urls["thumbnail"] = thumbnail_url

        print(f"✅ Task {task_id} complete:", supabase_urls)
        
        return {
            "status": "success",
            "message": "Models generated & uploaded",
            "file_urls": supabase_urls
        }
        
    except asyncio.CancelledError:
        print(f"❌ Task {task_id} was cancelled (CancelledError)")
        # Cleanup uploaded files
        for f in saved_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception as e:
                    print(f"Failed to remove {f}: {e}")
        raise  # Re-raise to properly handle cancellation
    except Exception as e:
        print(f"❌ Task {task_id} failed: {str(e)}")
        return {"status": "error", "message": str(e)}
    finally:
        # Remove from active tasks
        if task_id in active_tasks:
            del active_tasks[task_id]
            print(f"🗑️ Task {task_id} removed from active tasks")


@app.post("/generate-3d-model")
async def generate_3d_model(
    request: Request,
    files: List[UploadFile] = File(...)
):
    # Generate unique task ID
    task_id = f"task_{int(time.time() * 1000)}"
    
    saved_files = []

    # Save uploaded images
    for f in files:
        save_path = os.path.join(UPLOAD_DIR, f.filename)
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(f.file, buffer)
        saved_files.append(save_path)

    print(f"📸 Received {len(saved_files)} images. Task ID: {task_id}")

    # Check if client disconnected before starting
    if await request.is_disconnected():
        print(f"❌ Client disconnected before starting task {task_id}")
        # Cleanup uploaded files
        for f in saved_files:
            if os.path.exists(f):
                os.remove(f)
        return {"status": "cancelled", "message": "Client disconnected"}

    # Create background task
    task = asyncio.create_task(process_3d_generation(saved_files, task_id))
    active_tasks[task_id] = task

    # Monitor for client disconnect
    async def monitor_disconnect():
        try:
            while not task.done():
                if await request.is_disconnected():
                    print(f"❌ Client disconnected, cancelling task {task_id}")
                    task.cancel()
                    if task_id in active_tasks:
                        del active_tasks[task_id]
                    break
                await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Error in disconnect monitor: {e}")

    # Start disconnect monitor
    asyncio.create_task(monitor_disconnect())

    # Wait for completion
    try:
        result = await task
        return result
    except asyncio.CancelledError:
        return {"status": "cancelled", "message": "Generation was cancelled"}


@app.post("/cancel-generation/{task_id}")
async def cancel_generation(task_id: str):
    """Explicit endpoint to cancel a generation task"""
    if task_id in active_tasks:
        task = active_tasks[task_id]
        if not task.done():
            task.cancel()
            print(f"❌ Manually cancelled task {task_id}")
            return {"status": "success", "message": f"Task {task_id} cancelled"}
        else:
            return {"status": "error", "message": "Task already completed"}
    else:
        return {"status": "error", "message": "Task not found"}


@app.get("/task-status/{task_id}")
async def get_task_status(task_id: str):
    """Check status of a generation task"""
    if task_id in active_tasks:
        task = active_tasks[task_id]
        if task.done():
            try:
                result = task.result()
                return {
                    "status": "completed", 
                    "task_id": task_id,
                    "result": result
                }
            except Exception as e:
                return {
                    "status": "failed",
                    "task_id": task_id,
                    "error": str(e)
                }
        else:
            return {"status": "processing", "task_id": task_id}
    else:
        return {"status": "not_found", "task_id": task_id}


@app.get("/output/{filename}")
async def serve_model(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        return {"error": "Not found"}
    return FileResponse(file_path)