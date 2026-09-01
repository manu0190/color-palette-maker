# Color Palette Maker

A simple web application that converts color palette data from a JSON file into a clean, downloadable PNG palette.

You can either drag and drop a JSON file or choose one from your device. The application processes the file through a FastAPI backend and generates a neatly formatted palette image.

## Features

- Drag-and-drop JSON file upload
- Choose a JSON file from your device
- Automatically extracts colors from the JSON
- Converts RGB color values to HEX
- Generates a clean PNG palette
- Displays color swatches with HEX values
- Download the generated palette as a PNG
- Responsive frontend
- FastAPI backend
- Works locally through a browser
- Designed to be deployable as a web application

## How It Works

The application follows a simple frontend/backend architecture:

```text
JSON File
    │
    ▼
Frontend
HTML + CSS + JavaScript
    │
    │ POST /generate
    ▼
FastAPI Backend
    │
    ▼
Python Palette Generator
    │
    ▼
PNG Palette
    │
    ▼
Browser
    │
    ▼
Download PNG
