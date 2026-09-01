# 🎨 ColorFoundry — Smart Paint Palette & Opacity Engine

**ColorFoundry** is an intelligent color extraction and palette generation engine designed for artists and digital painters. 

Most palette generators extract colors based purely on pixel frequency or simple clustering (k-means), which fills your palette with repetitive, washed-out shades caused by transparency, glaze layers, or atmospheric haze. 

ColorFoundry solves this by using **3D color space ray convergence** and **alpha compositing validation** to mathematically differentiate between **genuinely distinct pigments** and **translucent appearances of the same underlying color**.

---

## ✨ Features

- **Opacity-Aware Deduplication:** Identifies when multiple observed colors are merely the same base color washed over different backgrounds at varying opacities ($\alpha$).
- **Linear RGB Optical Math:** Performs color mixing and projection in linear color space to accurately model physical light and paint wash dynamics.
- **SLIC Superpixel Topological Graph:** Segments images into locally cohesive regions and analyzes neighbor contact perimeters to estimate underlying backdrops ($B$).
- **Multi-Ray Least-Squares Solver:** Solves the geometric convergence of 3D color vectors to discover latent source pigments ($F$) and their exact opacity levels.
- **Dual Mode API & Web Interface:** Includes a FastAPI web service supporting direct photo uploads or raw JSON palette definitions to generate printable palette cards.

---

## 🧠 How It Works (The Mathematics)

In standard alpha blending, an observed color $I$ is formed by:

$$I = \alpha \cdot F + (1 - \alpha) \cdot B$$

Where:
- $F$ is the true, opaque foreground pigment.
- $B$ is the local underlying background.
- $\alpha \in [0, 1]$ is the opacity level.

                Input Photograph
                       │
                       ▼
      [1. SLIC Superpixel Segmentation]
          (Extract region I and neighbors)
                       │
                       ▼
      [2. Topological Background Estimation]
          (Determine local backdrop B)
                       │
                       ▼
      [3. Forward Ray Casting (3D RGB Space)]
          Ray: R(t) = B + t(I - B),  t ≥ 1.0
                       │
                       ▼
      [4. RANSAC Multi-Ray Least Squares]
          (Find convergent latent F intersections)
                       │
                       ▼
      [5. Alpha Reconstruction Validation]
          (Verify residual: ||I - (αF + (1-α)B)|| < ε)
                       │
         ┌─────────────┴─────────────┐
         ▼                           ▼
[Valid Opacity Variant]     [Independent Pigment]
Collapsed into Latent F     Preserved as Unique Swatch
         │                           │
         └─────────────┬─────────────┘
                       ▼
         Clean Artist Palette (JSON & PNG)



---

## 📁 Project Structure

```text
color_palette_maker/
├── backend/
│   ├── __init__.py
│   ├── candidate_discovery.py # RANSAC multi-ray least-squares solver & NMS
│   ├── color_pipeline.py      # End-to-end extraction orchestrator
│   └── image_colors.py        # Superpixel topologies, background estimators & validators
├── frontend/
│   ├── index.html             # Web UI interface
│   ├── script.js              # Frontend upload and rendering logic
│   └── style.css              # Styling
├── test_images/               # Reference photos for benchmarking
├── main.py                    # FastAPI server endpoints
├── palette.py                 # Matplotlib palette card renderer
├── requirements.txt           # Project dependencies
└── README.md

git clone [https://github.com/your-username/color-palette-maker.git](https://github.com/manu0190/color-palette-maker.git)
cd color-palette-maker

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt


# Run the extraction pipeline on an image
python -m backend.color_pipeline

# Render the PNG card from palette.json
python -c "from palette import generate_palette_png; generate_palette_png('palette.json')"

run:-
uvicorn main:app --reload --port 8000


output schema
1. image
2. JSON
{
  "source_image": "p1.avif",
  "palette_size": 48,
  "latent_families_resolved": 13,
  "colors": [
    {
      "hex": "#004973",
      "rgb": [0, 73, 115],
      "type": "latent_underlying_color",
      "pixel_weight": 31166,
      "variants_collapsed": 3,
      "recovered_opacities": [0.308, 0.35, 0.574]
    },
    {
      "hex": "#635f33",
      "rgb": [99, 95, 51],
      "type": "unique_independent_color",
      "pixel_weight": 3305,
      "variants_collapsed": 0,
      "recovered_opacities": [1.0]
    }
  ]
}
