import json
import os

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


def load_colors(json_file):
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Support both "swatches" and "colors" schemas
    swatch_list = data.get("swatches") or data.get("colors") or []
    
    colors = []
    for swatch in swatch_list:
        # Handles {"hex": "#..."} or {"color": "#..."} or {"rgb": [...]}
        if "hex" in swatch:
            colors.append(swatch["hex"])
        elif "rgb" in swatch:
            colors.append(tuple(swatch["rgb"]))
        elif "color" in swatch:
            colors.append(swatch["color"])

    return colors


def generate_palette_png(json_file):
    """
    Read a JSON palette and generate a PNG image.
    """

    # Get colors
    colors = load_colors(json_file)

    # Get palette name
    with open(json_file, "r") as file:
        data = json.load(file)

    palette_name = data.get(
        "name",
        "Color Palette"
    )

    number_of_colors = len(colors)

    # -----------------------------------
    # Grid
    # -----------------------------------

    columns = min(
        5,
        max(1, int(number_of_colors ** 0.5 + 0.5))
    )

    rows = (
        number_of_colors + columns - 1
    ) // columns

    # -----------------------------------
    # Layout
    # -----------------------------------

    box_size = 1.5
    horizontal_gap = 0.35
    vertical_gap = 0.65

    left_padding = 0.8
    right_padding = 0.8
    top_padding = 1.3
    bottom_padding = 0.8

    width = (
        left_padding
        + columns * box_size
        + (columns - 1) * horizontal_gap
        + right_padding
    )

    height = (
        top_padding
        + rows * (box_size + vertical_gap)
        + bottom_padding
    )

    # -----------------------------------
    # Create figure
    # -----------------------------------

    fig, ax = plt.subplots(
        figsize=(width, height)
    )

    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # -----------------------------------
    # Draw colors
    # -----------------------------------

    for index, color in enumerate(colors):

        row = index // columns
        column = index % columns

        x = (
            left_padding
            + column * (box_size + horizontal_gap)
        )

        y = (
            height
            - top_padding
            - (row + 1) * box_size
            - row * vertical_gap
        )

        # Color square
        ax.add_patch(
            plt.Rectangle(
                (x, y),
                box_size,
                box_size,
                facecolor=color,
                edgecolor="none"
            )
        )

        # HEX code
        ax.text(
            x + box_size / 2,
            y - 0.18,
            color,
            ha="center",
            va="top",
            fontsize=9
        )

    # -----------------------------------
    # Title
    # -----------------------------------

    ax.text(
        width / 2,
        height - 0.45,
        palette_name,
        ha="center",
        va="center",
        fontsize=18,
        fontweight="bold"
    )

    # -----------------------------------
    # Clean up
    # -----------------------------------

    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis("off")

    # -----------------------------------
    # Output
    # -----------------------------------

    folder = os.path.dirname(json_file)

    output_file = os.path.join(
        folder,
        "palette.png"
    )

    plt.savefig(
        output_file,
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
        pad_inches=0.1
    )

    plt.close()

    return output_file