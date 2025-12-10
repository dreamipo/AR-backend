import os
import asyncio
from typing import Optional
from tripo3d import TripoClient, TaskStatus
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("TRIPO3D_API_KEY")

# Track active tasks for cancellation
# This will be imported from main.py
active_tasks = {}


async def generate_3d_from_images(
    image_paths: list[str], 
    formats: list[str] = ['glb', 'usdz'],
    task_id: Optional[str] = None
):
    """
    Generate 3D model using Tripo3D SDK (single or multi-view)
    with cancellation support.
    
    Args:
        image_paths: List of image file paths
        formats: List of output formats (glb, usdz, etc.)
        task_id: Optional task ID for cancellation tracking
    """
    output_dir = "./output"
    os.makedirs(output_dir, exist_ok=True)

    async with TripoClient(api_key=API_KEY) as client:
        try:
            # Check cancellation before starting
            if task_id and task_id not in active_tasks:
                print(f"❌ Task {task_id} cancelled before generation")
                return {"status": "cancelled", "message": "Task cancelled"}

            # Choose method based on number of images
            if len(image_paths) == 1:
                print(f"🖼️ Generating 3D model from single image... (Task: {task_id})")
                tripo_task_id = await client.image_to_model(image=image_paths[0])
            else:
                print(f"🖼️ Generating 3D model from {len(image_paths)} images (multi-view)... (Task: {task_id})")
                tripo_task_id = await client.multiview_to_model(images=image_paths)

            print(f"🚀 Tripo task started: {tripo_task_id}")

            # Custom polling loop with cancellation checks
            max_wait_time = 300  # 5 minutes
            poll_interval = 3  # Check every 3 seconds
            elapsed_time = 0

            while elapsed_time < max_wait_time:
                # Check if task was cancelled
                if task_id and task_id not in active_tasks:
                    print(f"❌ Task {task_id} cancelled during generation")
                    return {"status": "cancelled", "message": "Task cancelled by user"}

                # Poll task status
                task = await client.get_task(tripo_task_id)
                
                print(f"📊 Status: {task.status} (elapsed: {elapsed_time}s)")

                if task.status == TaskStatus.SUCCESS:
                    print("✅ Base 3D model generated.")
                    break
                elif task.status == TaskStatus.FAILED:
                    print("❌ Task failed:", task)
                    return {"status": "failed", "details": str(task)}
                elif task.status == TaskStatus.CANCELLED:
                    print("❌ Task was cancelled on Tripo server")
                    return {"status": "cancelled", "message": "Task cancelled on server"}

                # Wait before next poll
                await asyncio.sleep(poll_interval)
                elapsed_time += poll_interval

            if elapsed_time >= max_wait_time:
                print("❌ Task timeout")
                return {"status": "error", "message": "Task timeout"}

            # Check cancellation before download
            if task_id and task_id not in active_tasks:
                print(f"❌ Task {task_id} cancelled before download")
                return {"status": "cancelled", "message": "Task cancelled"}

            # Download base file (GLB)
            print("📥 Downloading base model...")
            default_files = await client.download_task_models(task, output_dir)
            print(f"📥 Downloaded base files: {default_files}")

            # Get PBR model path
            pbr_model = default_files.get("pbr_model")

            output_files = {}

            # Convert to additional formats
            for fmt in formats:
                # Check cancellation before each format conversion
                if task_id and task_id not in active_tasks:
                    print(f"❌ Task {task_id} cancelled during format conversion")
                    return {"status": "cancelled", "message": "Task cancelled"}

                try:
                    format_dir = os.path.join(output_dir, fmt)
                    os.makedirs(format_dir, exist_ok=True)

                    if fmt == "glb":
                        if pbr_model:
                            output_files.setdefault("glb", []).append(pbr_model)
                            print(f"✔ GLB ready: {pbr_model}")
                        continue

                    print(f"🔄 Converting GLB → {fmt.upper()} ...")
                    convert_task_id = await client.convert_model(
                        original_model_task_id=tripo_task_id,
                        format=fmt
                    )

                    # Poll conversion task with cancellation checks
                    convert_elapsed = 0
                    convert_max_wait = 120  # 2 minutes for conversion
                    
                    while convert_elapsed < convert_max_wait:
                        # Check cancellation
                        if task_id and task_id not in active_tasks:
                            print(f"❌ Task {task_id} cancelled during {fmt} conversion")
                            return {"status": "cancelled", "message": "Task cancelled"}

                        convert_task = await client.get_task(convert_task_id)
                        
                        if convert_task.status == TaskStatus.SUCCESS:
                            converted = await client.download_task_models(convert_task, format_dir)
                            paths = [p for p in converted.values() if p]
                            output_files[fmt] = paths
                            print(f"✔ {fmt.upper()} saved: {paths}")
                            break
                        elif convert_task.status == TaskStatus.FAILED:
                            print(f"❌ Conversion to {fmt.upper()} failed")
                            break
                        
                        await asyncio.sleep(poll_interval)
                        convert_elapsed += poll_interval

                    if convert_elapsed >= convert_max_wait:
                        print(f"⚠️ Conversion to {fmt.upper()} timed out")

                except Exception as e:
                    print(f"❌ Conversion error for {fmt.upper()}: {e}")

            # Final cancellation check
            if task_id and task_id not in active_tasks:
                print(f"❌ Task {task_id} cancelled at completion")
                return {"status": "cancelled", "message": "Task cancelled"}

            return {
                "status": "success",
                "task_id": tripo_task_id,
                "pbr_model": pbr_model,
                "files": output_files
            }

        except asyncio.CancelledError:
            print(f"❌ Task {task_id} cancelled via asyncio.CancelledError")
            return {"status": "cancelled", "message": "Task was cancelled"}
        except Exception as e:
            print(f"❌ Error in generation: {e}")
            return {"status": "error", "message": str(e)}