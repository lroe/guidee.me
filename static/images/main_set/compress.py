import os
from PIL import Image

def quantize_png(directory="."):
    for filename in os.listdir(directory):
        if filename.lower().endswith(".png"):
            filepath = os.path.join(directory, filename)
            try:
                img = Image.open(filepath)

                # Convert to palette-based (max 256 colors)
                img = img.convert("P", palette=Image.ADAPTIVE)

                img.save(filepath, optimize=True)
                print(f"Quantized and compressed: {filename}")
            except Exception as e:
                print(f"Failed: {filename}, {e}")

if __name__ == "__main__":
    quantize_png(".")
