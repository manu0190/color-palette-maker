from pathlib import Path
import tempfile

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from palette import generate_palette_png


# -----------------------------------
# Project paths
# -----------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

FRONTEND_DIR = BASE_DIR / "frontend"


# -----------------------------------
# FastAPI
# -----------------------------------

app = FastAPI(
    title="Color Palette Maker API"
)


# -----------------------------------
# Frontend
# -----------------------------------

app.mount(
    "/static",
    StaticFiles(directory=FRONTEND_DIR),
    name="static"
)


@app.get("/")
def frontend():

    return FileResponse(
        FRONTEND_DIR / "index.html"
    )


# -----------------------------------
# API
# -----------------------------------

@app.post("/generate")
async def generate_palette(
    file: UploadFile = File(...)
):

    # Check file type
    if not file.filename.lower().endswith(".json"):

        raise HTTPException(
            status_code=400,
            detail="Please upload a JSON file."
        )


    # Temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:

        temp_dir = Path(temp_dir)

        # Temporary JSON file
        json_path = temp_dir / "palette.json"


        # Save uploaded JSON
        contents = await file.read()

        json_path.write_bytes(contents)


        try:

            # Generate PNG
            png_path = generate_palette_png(
                str(json_path)
            )


            # Read PNG into memory
            png_bytes = Path(
                png_path
            ).read_bytes()


        except Exception as error:

            raise HTTPException(
                status_code=400,
                detail=f"Could not generate palette: {error}"
            )


        # Return PNG
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={
                "Content-Disposition":
                    'attachment; filename="palette.png"'
            }
        )