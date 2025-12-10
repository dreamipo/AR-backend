import os
from supabase import create_client, Client

# Load environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise Exception("❌ Missing SUPABASE_URL or SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def upload_to_supabase(local_path: str, dest_path: str, bucket: str = None) -> str:
    """
    Upload ANY file (model or thumbnail) to Supabase Storage
    and return a public URL.
    """
    bucket = bucket or SUPABASE_BUCKET

    if not bucket:
        raise Exception("❌ No bucket name provided")

    if not os.path.exists(local_path):
        raise FileNotFoundError(f"❌ File not found: {local_path}")

    # Read file bytes
    with open(local_path, "rb") as file_obj:
        file_bytes = file_obj.read()

    # Upload file
    response = supabase.storage.from_(bucket).upload(dest_path, file_bytes)

    # Check Supabase response
    if isinstance(response, dict) and response.get("error"):
        raise Exception(f"❌ Upload failed: {response['error']['message']}")

    # Get public URL
    public_url = supabase.storage.from_(bucket).get_public_url(dest_path)

    return public_url
