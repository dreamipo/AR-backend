import os
import asyncio
from tripo3d import TripoClient, TaskStatus
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("TRIPO3D_API_KEY")

async def generate_3d_from_images(image_paths: list[str]):
    """
    Uses the Tripo3D SDK to generate 3D models from single or multiple images.
    Returns: dict with status and model file URLs
    """
    async with TripoClient(api_key=API_KEY) as client:
        try:
            # Choose method based on number of images
            if len(image_paths) == 1:
                print("🖼️ Generating 3D model from single image...")
                task_id = await client.image_to_model(image=image_paths[0])
            else:
                print(f"🖼️ Generating 3D model from {len(image_paths)} images (multi-view)...")
                task_id = await client.multiview_to_model(images=image_paths)

            print(f"🚀 Task started: {task_id}")
            task = await client.wait_for_task(task_id, verbose=True)

            if task.status == TaskStatus.SUCCESS:
                print("✅ 3D model generation complete.")
                files = await client.download_task_models(task, "./output")
                return {"status": "success", "files": files}
            else:
                print("❌ Task failed:", task)
                return {"status": "failed", "details": str(task)}

        except Exception as e:
            print("⚠️ Error:", e)
            return {"status": "error", "message": str(e)}
