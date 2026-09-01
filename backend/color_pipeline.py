import os
import json
import cv2
import numpy as np
from skimage.segmentation import slic
from skimage.measure import regionprops
from typing import List, Dict, Any

from backend.image_colors import (
    SuperpixelInfo,
    LocalBackgroundEstimator,
    ObservedSwatch
)

from backend.candidate_discovery import (
    RobustCandidateEngine,
    ResolvedColorFamily
)


# ============================================================
# COLOR SPACE CONVERSION
# ============================================================

def srgb_to_linear(img_srgb: np.ndarray) -> np.ndarray:
    """
    Convert gamma-encoded sRGB [0-255]
    to linear RGB [0-1].
    """

    img = img_srgb.astype(np.float32) / 255.0

    mask = img > 0.04045

    img[mask] = np.power(
        (img[mask] + 0.055) / 1.055,
        2.4
    )

    img[~mask] = img[~mask] / 12.92

    return img


def linear_to_srgb(img_lin: np.ndarray) -> np.ndarray:
    """
    Convert linear RGB [0-1]
    back to sRGB [0-255].
    """

    img = np.clip(
        img_lin,
        0.0,
        1.0
    )

    mask = img > 0.0031308

    img[mask] = (
        1.055
        * np.power(img[mask], 1.0 / 2.4)
        - 0.055
    )

    img[~mask] = 12.92 * img[~mask]

    return np.clip(
        img * 255.0,
        0,
        255
    ).astype(np.uint8)


def rgb_to_hex(rgb_255: np.ndarray) -> str:
    """
    Convert RGB [0-255] to HEX.
    """

    r, g, b = [
        int(np.clip(c, 0, 255))
        for c in rgb_255
    ]

    return f"#{r:02x}{g:02x}{b:02x}"


# ============================================================
# MAIN COLOR FOUNDRY PIPELINE
# ============================================================

class ColorFoundryPipeline:

    def __init__(
        self,
        n_segments: int = 250,
        slic_compactness: float = 10.0,
        residual_thresh: float = 0.04,
        min_contrast: float = 0.03,
        target_palette_size: int = 48
    ):

        self.n_segments = n_segments

        self.compactness = slic_compactness

        self.bg_estimator = LocalBackgroundEstimator(
            continuity_dist_thresh=0.10,
            cluster_merge_thresh=0.08
        )

        self.candidate_engine = RobustCandidateEngine(
            residual_thresh=residual_thresh,
            min_contrast=min_contrast
        )

        self.target_palette_size = target_palette_size


    # ========================================================
    # SLIC SUPERPIXELS
    # ========================================================

    def extract_superpixels(
        self,
        img_linear: np.ndarray
    ):

        labels = slic(
            img_linear,
            n_segments=self.n_segments,
            compactness=self.compactness,
            start_label=0,
            channel_axis=2
        )

        props = regionprops(
            labels + 1
        )

        sp_dict: Dict[int, SuperpixelInfo] = {}

        for p in props:

            sp_id = p.label - 1

            mask = (
                labels == sp_id
            )

            mean_color = np.mean(
                img_linear[mask],
                axis=0
            ).astype(np.float32)

            centroid_xy = np.array(
                [
                    p.centroid[1],
                    p.centroid[0]
                ],
                dtype=np.float32
            )

            sp_dict[sp_id] = SuperpixelInfo(
                id=sp_id,
                mean_rgb=mean_color,
                center_xy=centroid_xy,
                pixel_count=p.area,
                boundary_contact_len=0
            )


        # ----------------------------------------------------
        # BUILD ADJACENCY GRAPH
        # ----------------------------------------------------

        adjacency: Dict[
            int,
            Dict[int, int]
        ] = {
            i: {}
            for i in sp_dict
        }

        # Vertical boundaries

        v_diff = (
            labels[:-1, :]
            != labels[1:, :]
        )

        for r, c in zip(
            *np.where(v_diff)
        ):

            l1 = labels[r, c]
            l2 = labels[r + 1, c]

            adjacency[l1][l2] = (
                adjacency[l1].get(l2, 0)
                + 1
            )

            adjacency[l2][l1] = (
                adjacency[l2].get(l1, 0)
                + 1
            )


        # Horizontal boundaries

        h_diff = (
            labels[:, :-1]
            != labels[:, 1:]
        )

        for r, c in zip(
            *np.where(h_diff)
        ):

            l1 = labels[r, c]
            l2 = labels[r, c + 1]

            adjacency[l1][l2] = (
                adjacency[l1].get(l2, 0)
                + 1
            )

            adjacency[l2][l1] = (
                adjacency[l2].get(l1, 0)
                + 1
            )


        return (
            labels,
            sp_dict,
            adjacency
        )


    # ========================================================
    # COMPLETE IMAGE PROCESSING
    # ========================================================

    def process_image(
        self,
        image_path: str,
        output_json_path: str
    ) -> Dict[str, Any]:

        # ----------------------------------------------------
        # 1. LOAD IMAGE
        # ----------------------------------------------------

        bgr = cv2.imread(
            image_path
        )

        if bgr is None:
            raise FileNotFoundError(
                f"Could not open image: {image_path}"
            )

        rgb = cv2.cvtColor(
            bgr,
            cv2.COLOR_BGR2RGB
        )

        img_linear = srgb_to_linear(
            rgb
        )

        print(
            f"Loaded image: "
            f"{image_path} "
            f"({rgb.shape[1]}x{rgb.shape[0]})"
        )


        # ----------------------------------------------------
        # 2. SLIC
        # ----------------------------------------------------

        labels, superpixels, adjacency = (
            self.extract_superpixels(
                img_linear
            )
        )

        print(
            f"Extracted "
            f"{len(superpixels)} "
            f"superpixel regions via SLIC."
        )


        # ----------------------------------------------------
        # 3. LOCAL BACKGROUND ESTIMATION
        # ----------------------------------------------------

        swatches: List[
            ObservedSwatch
        ] = []


        for sp_id, sp in superpixels.items():

            neighbor_ids = adjacency.get(
                sp_id,
                {}
            )

            if not neighbor_ids:
                continue


            neighbor_infos = []


            for n_id, contact_len in (
                neighbor_ids.items()
            ):

                n_info = superpixels[n_id]

                neighbor_infos.append(
                    SuperpixelInfo(
                        id=n_info.id,
                        mean_rgb=n_info.mean_rgb,
                        center_xy=n_info.center_xy,
                        pixel_count=n_info.pixel_count,
                        boundary_contact_len=contact_len
                    )
                )


            bg_color, strategy, confidence = (
                self.bg_estimator.estimate_background(
                    sp,
                    neighbor_infos
                )
            )


            swatches.append(
                ObservedSwatch(
                    color=sp.mean_rgb,
                    background=bg_color,
                    pixel_count=sp.pixel_count
                )
            )


        print(
            f"Generated "
            f"{len(swatches)} "
            f"observed color/background swatches."
        )


        # ----------------------------------------------------
        # 4. FIND LATENT COLORS
        # ----------------------------------------------------

        resolved_families: List[ResolvedColorFamily] = (
            self.candidate_engine.resolve_color_families(swatches)
        )

        print(
            f"Identified {len(resolved_families)} latent color families "
            f"collapsing multi-opacity regions."
        )

        print("\n========================================")
        print("LATENT FAMILY DIAGNOSTICS")
        print("========================================")

        for i, fam in enumerate(resolved_families):
            F_srgb = linear_to_srgb(fam.true_color_rgb)

            print(
                f"Family {i:02d} | "
                f"F RGB: {F_srgb.tolist()} | "
                f"Swatches: {len(fam.explained_swatches)} | "
                f"Residual: {fam.total_residual:.5f} | "
                f"Alphas: "
                f"{[round(float(a), 3) for a in fam.opacities]}"
            )

        print("========================================\n")


        # ----------------------------------------------------
        # 5. FIND WHICH SWATCHES WERE EXPLAINED
        # ----------------------------------------------------

        explained_swatch_ids = set()


        for family in resolved_families:

            for swatch in (
                family.explained_swatches
            ):

                explained_swatch_ids.add(
                    id(swatch)
                )


        # ----------------------------------------------------
        # 6. BUILD FINAL PALETTE
        # ----------------------------------------------------

        final_palette_entries = []


        # ====================================================
        # A. LATENT UNDERLYING COLORS
        # ====================================================

        for family in resolved_families:

            srgb_value = linear_to_srgb(
                family.true_color_rgb
            )

            total_weight = sum(
                swatch.pixel_count
                for swatch
                in family.explained_swatches
            )


            final_palette_entries.append({

                "hex": rgb_to_hex(
                    srgb_value
                ),

                "rgb": [
                    int(c)
                    for c in srgb_value
                ],

                "type":
                    "latent_underlying_color",

                "pixel_weight":
                    int(total_weight),

                "variants_collapsed":
                    len(
                        family.explained_swatches
                    ),

                "recovered_opacities": [
                    round(
                        float(alpha),
                        3
                    )
                    for alpha
                    in family.opacities
                ]

            })


        # ====================================================
        # B. INDEPENDENT COLORS
        # ====================================================

        for swatch in swatches:

            if id(swatch) in (
                explained_swatch_ids
            ):
                continue


            srgb_value = linear_to_srgb(
                swatch.color
            )


            final_palette_entries.append({

                "hex": rgb_to_hex(
                    srgb_value
                ),

                "rgb": [
                    int(c)
                    for c in srgb_value
                ],

                "type":
                    "unique_independent_color",

                "pixel_weight":
                    int(
                        swatch.pixel_count
                    ),

                "variants_collapsed":
                    0,

                "recovered_opacities": [
                    1.0
                ]

            })


        # ----------------------------------------------------
        # 7. SORT BY PIXEL WEIGHT
        # ----------------------------------------------------

        final_palette_entries.sort(
            key=lambda x:
                x["pixel_weight"],
            reverse=True
        )


        # ----------------------------------------------------
        # 8. LIMIT PALETTE SIZE
        # ----------------------------------------------------

        if (
            self.target_palette_size
            is not None
            and len(final_palette_entries)
            > self.target_palette_size
        ):

            latents = [
                p
                for p
                in final_palette_entries
                if p["type"]
                == "latent_underlying_color"
            ]

            independents = [
                p
                for p
                in final_palette_entries
                if p["type"]
                == "unique_independent_color"
            ]


            remaining_slots = max(
                0,
                self.target_palette_size
                - len(latents)
            )


            final_palette_entries = (
                latents
                + independents[
                    :remaining_slots
                ]
            )


        # ----------------------------------------------------
        # 9. CREATE JSON
        # ----------------------------------------------------

        palette_output = {

            "source_image":
                os.path.basename(
                    image_path
                ),

            "palette_size":
                len(
                    final_palette_entries
                ),

            "latent_families_resolved":
                len(
                    resolved_families
                ),

            "colors":
                final_palette_entries
        }


        # ----------------------------------------------------
        # 10. SAVE JSON
        # ----------------------------------------------------

        with open(
            output_json_path,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                palette_output,
                f,
                indent=2
            )


        print(
            f"Successfully generated "
            f"palette with "
            f"{len(final_palette_entries)} "
            f"colors -> "
            f"{output_json_path}"
        )


        return palette_output



    # ============================================================
# DIRECT TEST RUN
# ============================================================

if __name__ == "__main__":

    print("\n========================================")
    print("COLOR FOUNDRY IMAGE PIPELINE")
    print("========================================")

    pipeline = ColorFoundryPipeline(
        n_segments=250,
        slic_compactness=10.0,
        residual_thresh=0.04,
        min_contrast=0.03,
        target_palette_size=48
    )

    test_img = "test_images/p1.avif"

    output_json = "palette.json"

    print(f"\nInput image: {test_img}")
    print("Starting image analysis...\n")

    result = pipeline.process_image(
        image_path=test_img,
        output_json_path=output_json
    )

    print("\n========================================")
    print("PIPELINE COMPLETE")
    print("========================================")
    print(f"Palette size: {result['palette_size']}")
    print(f"Latent families: {result['latent_families_resolved']}")
    print(f"Output: {output_json}")