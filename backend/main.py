from pathlib import Path
import tempfile

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.color_pipeline import ColorFoundryPipeline
from palette import generate_palette_png


# ============================================================
# PROJECT PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Color Palette Maker API",
    version="1.0.0",
)


# ============================================================
# FRONTEND
# ============================================================

app.mount(
    "/static",
    StaticFiles(directory=FRONTEND_DIR),
    name="static",
)


@app.get("/")
def frontend():
    return FileResponse(FRONTEND_DIR / "index.html")


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "Color Palette Maker",
    }


# ============================================================
# JSON → PNG
# ============================================================

@app.post("/generate")
async def generate_palette(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    if not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Please upload a JSON palette file.")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)
        json_path = temp_dir / "palette.json"

        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded JSON file is empty.")

        json_path.write_bytes(contents)

        try:
            png_path = generate_palette_png(str(json_path))
            png_bytes = Path(png_path).read_bytes()
        except Exception as error:
            raise HTTPException(status_code=400, detail=f"Could not generate palette: {error}")

        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Content-Disposition": 'inline; filename="palette.png"'},
        )


# ============================================================
# IMAGE → PNG
# ============================================================

@app.post("/extract-from-image")
async def extract_palette_from_image(
    file: UploadFile = File(...),
    n_segments: int = Form(250),
    target_palette_size: int = Form(18),
):
    allowed_extensions = {".jpg", ".jpeg", ".png", ".webp", ".avif"}

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file was provided.")

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image format. Allowed: {', '.join(sorted(allowed_extensions))}",
        )

    if not 50 <= n_segments <= 1000:
        raise HTTPException(status_code=400, detail="n_segments must be between 50 and 1000.")

    if not 4 <= target_palette_size <= 100:
        raise HTTPException(status_code=400, detail="target_palette_size must be between 4 and 100.")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)
        image_path = temp_dir / f"input{file_ext}"
        json_path = temp_dir / "palette.json"

        image_bytes = await file.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="Uploaded image is empty.")

        image_path.write_bytes(image_bytes)

        try:
            pipeline = ColorFoundryPipeline(
                n_segments=n_segments,
                residual_thresh=0.04,
                target_palette_size=target_palette_size,
                min_color_distance=16.0
            )

            pipeline.process_image(
                image_path=str(image_path),
                output_json_path=str(json_path),
            )

            png_path = generate_palette_png(str(json_path))
            png_bytes = Path(png_path).read_bytes()

        except Exception as error:
            raise HTTPException(
                status_code=500,
                detail=f"Color extraction failed: {error}",
            )

        output_name = f"{Path(file.filename).stem}_palette.png"
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Content-Disposition": f'inline; filename="{output_name}"'},
        )