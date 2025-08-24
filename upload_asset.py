
import os
import argparse
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from pathlib import Path

def upload_to_cloudinary(file_path, folder_name):
    """
    Uploads a local file to a specified folder in Cloudinary and returns the secure URL.
    """
    # --- 1. Load Environment Variables ---
    # This loads the credentials from your .env file
    load_dotenv()

    # --- 2. Check for Cloudinary Credentials ---
    cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME')
    api_key = os.getenv('CLOUDINARY_API_KEY')
    api_secret = os.getenv('CLOUDINARY_API_SECRET')

    if not all([cloud_name, api_key, api_secret]):
        print("❌ Error: Cloudinary credentials not found in your .env file.")
        print("Please make sure CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET are set.")
        return

    # --- 3. Configure Cloudinary SDK ---
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True
    )

    # --- 4. Prepare for Upload ---
    # Use the filename (without extension) as the public ID in Cloudinary
    # This makes the URL cleaner. e.g., 'aswathy' from 'aswathy.png'
    public_id = Path(file_path).stem

    try:
        print(f"⏳ Uploading '{file_path}' to Cloudinary folder '{folder_name}'...")
        
        # --- 5. Perform the Upload ---
        upload_result = cloudinary.uploader.upload(
            file_path,
            folder=folder_name,
            public_id=public_id,
            overwrite=True,
            resource_type="auto" # Let Cloudinary detect if it's an image, video, etc.
        )
        
        secure_url = upload_result.get('secure_url')
        
        print("\n✅ Success!")
        print(f"🔗 Public URL: {secure_url}")
        
        # Optionally, print the full Cloudinary path for reference
        full_path = upload_result.get('public_id')
        print(f"☁️  Cloudinary Path: {full_path}")

    except Exception as e:
        print(f"\n❌ Error during upload: {e}")

def main():
    # --- Set up Command-Line Argument Parser ---
    parser = argparse.ArgumentParser(description="Upload a game asset to Cloudinary.")
    
    # Required argument: The path to the file you want to upload
    parser.add_argument("file_path", help="The local path to the asset file (e.g., static/images/girl.png).")
    
    # Optional argument: The folder name in Cloudinary to organize assets
    parser.add_argument("-f", "--folder", default="game_assets", help="The Cloudinary folder to upload the asset to. (default: game_assets)")

    args = parser.parse_args()

    # --- Validate that the file actually exists before trying to upload ---
    if not os.path.exists(args.file_path):
        print(f"❌ Error: File not found at path '{args.file_path}'")
        return

    upload_to_cloudinary(args.file_path, args.folder)

if __name__ == "__main__":
    main()