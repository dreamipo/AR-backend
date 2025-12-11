import os
from tripo3d import TripoClient, TaskStatus
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("TRIPO3D_API_KEY")


async def generate_3d_from_images(image_paths: list[str], formats: list[str] = ['glb', 'usdz']):
    """
    Generate 3D model using Tripo3D SDK (single or multi-view)
    Then convert to formats like GLB + USDZ.
    """
    output_dir = "./output"
    os.makedirs(output_dir, exist_ok=True)

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

            if task.status != TaskStatus.SUCCESS:
                print("❌ Task failed:", task)
                return {"status": "failed", "details": str(task)}

            print("✅ Base 3D model generated.")

            # Download base file (GLB)
            default_files = await client.download_task_models(task, output_dir)
            print(f"📥 Downloaded base files: {default_files}")

            # FIX: Correct key is 'pbr_model'
            pbr_model = default_files.get("pbr_model")

            output_files = {}

            # Convert to additional formats
            for fmt in formats:
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
                        original_model_task_id=task_id,
                        format=fmt
                    )

                    convert_task = await client.wait_for_task(convert_task_id, verbose=True)

                    if convert_task.status == TaskStatus.SUCCESS:
                        converted = await client.download_task_models(convert_task, format_dir)
                        paths = [p for p in converted.values() if p]
                        output_files[fmt] = paths
                        print(f"✔ {fmt.upper()} saved: {paths}")
                    else:
                        print(f"Conversion to {fmt.upper()} failed")

                except Exception as e:
                    print(f"Conversion error for {fmt.upper()}: {e}")

            return {
                "status": "success",
                "task_id": task_id,
                "pbr_model": pbr_model,
                "files": output_files
            }

        except Exception as e:
            print("Error:", e)
            return {"status": "error", "message": str(e)}
