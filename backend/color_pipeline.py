import os
import json
import cv2
import numpy as np
from skimage.segmentation import slic
from skimage.measure import regionprops
from typing import List, Dict, Any, Optional

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
# COLOR SPACE CONVERSIONS & CIEDE2000
# ============================================================

def srgb_to_linear(img_srgb: np.ndarray) -> np.ndarray:
    img = img_srgb.astype(np.float32) / 255.0
    mask = img > 0.04045
    img[mask] = np.power((img[mask] + 0.055) / 1.055, 2.4)
    img[~mask] = img[~mask] / 12.92
    return img


def linear_to_srgb(img_lin: np.ndarray) -> np.ndarray:
    img = np.clip(img_lin, 0.0, 1.0)
    mask = img > 0.0031308
    img[mask] = 1.055 * np.power(img[mask], 1.0 / 2.4) - 0.055
    img[~mask] = 12.92 * img[~mask]
    return np.clip(img * 255.0, 0, 255).astype(np.uint8)


def rgb_to_hex(rgb_255: np.ndarray) -> str:
    r, g, b = [int(np.clip(c, 0, 255)) for c in rgb_255]
    return f"#{r:02x}{g:02x}{b:02x}"


def rgb_to_lab(rgb_255: np.ndarray) -> np.ndarray:
    pixel_bgr = np.uint8([[[int(rgb_255[2]), int(rgb_255[1]), int(rgb_255[0])]]])
    lab = cv2.cvtColor(pixel_bgr, cv2.COLOR_BGR2Lab)[0, 0].astype(np.float64)
    L = lab[0] * (100.0 / 255.0)
    a = lab[1] - 128.0
    b = lab[2] - 128.0
    return np.array([L, a, b], dtype=np.float64)


def ciede2000_distance(rgb1_255: np.ndarray, rgb2_255: np.ndarray) -> float:
    lab1 = rgb_to_lab(rgb1_255)
    lab2 = rgb_to_lab(rgb2_255)

    L1, a1, b1 = lab1[0], lab1[1], lab1[2]
    L2, a2, b2 = lab2[0], lab2[1], lab2[2]

    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    C_bar = (C1 + C2) / 2.0

    G = 0.5 * (1.0 - np.sqrt((C_bar ** 7) / ((C_bar ** 7) + (25.0 ** 7) + 1e-10)))

    a1_prime = (1.0 + G) * a1
    a2_prime = (1.0 + G) * a2

    C1_prime = np.hypot(a1_prime, b1)
    C2_prime = np.hypot(a2_prime, b2)

    h1_prime = np.degrees(np.arctan2(b1, a1_prime)) % 360.0
    h2_prime = np.degrees(np.arctan2(b2, a2_prime)) % 360.0

    delta_L_prime = L2 - L1
    delta_C_prime = C2_prime - C1_prime

    if C1_prime * C2_prime == 0:
        delta_h_prime = 0.0
    else:
        diff = h2_prime - h1_prime
        if abs(diff) <= 180.0:
            delta_h_prime = diff
        elif diff > 180.0:
            delta_h_prime = diff - 360.0
        else:
            delta_h_prime = diff + 360.0

    delta_H_prime = 2.0 * np.sqrt(C1_prime * C2_prime) * np.sin(np.radians(delta_h_prime / 2.0))

    L_bar_prime = (L1 + L2) / 2.0
    C_bar_prime = (C1_prime + C2_prime) / 2.0

    if C1_prime * C2_prime == 0:
        h_bar_prime = h1_prime + h2_prime
    else:
        diff = abs(h1_prime - h2_prime)
        if diff <= 180.0:
            h_bar_prime = (h1_prime + h2_prime) / 2.0
        elif (h1_prime + h2_prime) < 360.0:
            h_bar_prime = (h1_prime + h2_prime + 360.0) / 2.0
        else:
            h_bar_prime = (h1_prime + h2_prime - 360.0) / 2.0

    T = (
        1.0
        - 0.17 * np.cos(np.radians(h_bar_prime - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * h_bar_prime))
        + 0.32 * np.cos(np.radians(3.0 * h_bar_prime + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * h_bar_prime - 63.0))
    )

    S_L = 1.0 + ((0.015 * ((L_bar_prime - 50.0) ** 2)) / np.sqrt(20.0 + ((L_bar_prime - 50.0) ** 2)))
    S_C = 1.0 + 0.045 * C_bar_prime
    S_H = 1.0 + 0.015 * C_bar_prime * T

    delta_theta = 30.0 * np.exp(-(((h_bar_prime - 275.0) / 25.0) ** 2))
    R_C = 2.0 * np.sqrt((C_bar_prime ** 7) / ((C_bar_prime ** 7) + (25.0 ** 7) + 1e-10))
    R_T = -np.sin(np.radians(2.0 * delta_theta)) * R_C

    dE = np.sqrt(
        ((delta_L_prime / S_L) ** 2)
        + ((delta_C_prime / S_C) ** 2)
        + ((delta_H_prime / S_H) ** 2)
        + (R_T * (delta_C_prime / S_C) * (delta_H_prime / S_H))
    )

    return float(dE)


# ============================================================
# COLOR FOUNDRY PIPELINE
# ============================================================

class ColorFoundryPipeline:

    def __init__(
        self,
        n_segments: int = 650,
        slic_compactness: float = 14.0,
        residual_thresh: float = 0.035,
        min_contrast: float = 0.02,
        target_palette_size: Optional[int] = 32,
        min_color_distance: float = 2.8,
        min_ciede2000_dist: Optional[float] = None,
        **kwargs
    ):
        self.n_segments = n_segments
        self.compactness = slic_compactness
        self.min_color_distance = min_ciede2000_dist if min_ciede2000_dist is not None else min_color_distance
        self.target_palette_size = target_palette_size if target_palette_size else 32

        self.bg_estimator = LocalBackgroundEstimator(
            continuity_dist_thresh=0.08,
            cluster_merge_thresh=0.06
        )

        self.candidate_engine = RobustCandidateEngine(
            residual_thresh=residual_thresh,
            min_contrast=min_contrast
        )

    # ========================================================
    # DYNAMIC INTERPOLATION & SHADE HARMONIZATION
    # ========================================================

    def _generate_harmonic_shades(self, primary_colors: List[np.ndarray]) -> List[Dict[str, Any]]:
        """
        Synthesizes soft tints, deep undertones, and bridge shades 
        connected to the primary extracted artwork colors.
        """
        harmonic_entries = []
        for rgb in primary_colors:
            hsv = cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2HSV)[0, 0]
            h, s, v = int(hsv[0]), int(hsv[1]), int(hsv[2])

            # 1. Soft Highlight Tint (Higher lightness, slightly softer saturation)
            tint_s = max(10, int(s * 0.55))
            tint_v = min(245, int(v * 1.25) + 20)
            tint_rgb = cv2.cvtColor(np.uint8([[[h, tint_s, tint_v]]]), cv2.COLOR_HSV2RGB)[0, 0]

            # 2. Deep Shade Anchor (Lower lightness, deeper saturation)
            shade_s = min(255, int(s * 1.2))
            shade_v = max(20, int(v * 0.65))
            shade_rgb = cv2.cvtColor(np.uint8([[[h, shade_s, shade_v]]]), cv2.COLOR_HSV2RGB)[0, 0]

            for gen_rgb, shade_type in [(tint_rgb, "harmonic_tint"), (shade_rgb, "harmonic_deep_shade")]:
                lab = rgb_to_lab(gen_rgb)
                chroma = float(np.hypot(lab[1], lab[2]))
                harmonic_entries.append({
                    "hex": rgb_to_hex(gen_rgb),
                    "rgb": [int(c) for c in gen_rgb],
                    "type": shade_type,
                    "pixel_weight": 50,
                    "variants_collapsed": 0,
                    "recovered_opacities": [1.0],
                    "_score": 40000.0 + (chroma * 20.0),
                    "_srgb": gen_rgb
                })

        return harmonic_entries

    # ========================================================
    # SUPERPIXEL EXTRACTION
    # ========================================================

    def extract_superpixels(self, img_linear: np.ndarray, img_srgb: np.ndarray):
        h, w = img_linear.shape[:2]
        segments_to_use = int(np.clip((h * w) / 850.0, 500, 900))

        labels = slic(
            img_linear,
            n_segments=segments_to_use,
            compactness=self.compactness,
            start_label=0,
            channel_axis=2
        )

        props = regionprops(labels + 1)
        sp_dict: Dict[int, SuperpixelInfo] = {}

        hsv = cv2.cvtColor(img_srgb, cv2.COLOR_RGB2HSV)
        sat_map = hsv[:, :, 1]

        for p in props:
            sp_id = p.label - 1
            mask = (labels == sp_id)
            sp_sat = sat_map[mask]
            sp_pixels_lin = img_linear[mask]

            if len(sp_sat) > 0 and np.max(sp_sat) > 20:
                vibrant_mask = sp_sat >= np.percentile(sp_sat, 50)
                mean_color = np.mean(sp_pixels_lin[vibrant_mask], axis=0).astype(np.float32)
            else:
                mean_color = np.mean(sp_pixels_lin, axis=0).astype(np.float32)

            centroid_xy = np.array([p.centroid[1], p.centroid[0]], dtype=np.float32)

            sp_dict[sp_id] = SuperpixelInfo(
                id=sp_id,
                mean_rgb=mean_color,
                center_xy=centroid_xy,
                pixel_count=p.area,
                boundary_contact_len=0
            )

        adjacency: Dict[int, Dict[int, int]] = {i: {} for i in sp_dict}
        v_diff = (labels[:-1, :] != labels[1:, :])
        for r, c in zip(*np.where(v_diff)):
            l1, l2 = labels[r, c], labels[r + 1, c]
            adjacency[l1][l2] = adjacency[l1].get(l2, 0) + 1
            adjacency[l2][l1] = adjacency[l2].get(l1, 0) + 1

        h_diff = (labels[:, :-1] != labels[:, 1:])
        for r, c in zip(*np.where(h_diff)):
            l1, l2 = labels[r, c], labels[r, c + 1]
            adjacency[l1][l2] = adjacency[l1].get(l2, 0) + 1
            adjacency[l2][l1] = adjacency[l2].get(l1, 0) + 1

        return labels, sp_dict, adjacency

    # ========================================================
    # DIRECT CHROMATIC MINING
    # ========================================================

    def _extract_artistic_modes(self, rgb: np.ndarray) -> List[Dict[str, Any]]:
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        v = hsv[:, :, 2]
        valid_pixels = rgb[(v > 15) & (v < 252)]
        if len(valid_pixels) < 50:
            return []

        if len(valid_pixels) > 16000:
            idx = np.random.choice(len(valid_pixels), 16000, replace=False)
            sample = valid_pixels[idx].astype(np.float32)
        else:
            sample = valid_pixels.astype(np.float32)

        k = min(36, max(12, len(sample) // 80))
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.2)
        _, labels, centers = cv2.kmeans(sample, k, None, criteria, 6, cv2.KMEANS_PP_CENTERS)

        extracted = []
        for i, center in enumerate(centers):
            srgb_val = np.clip(center, 0, 255).astype(np.uint8)
            count = int(np.sum(labels == i))
            lab = rgb_to_lab(srgb_val)
            chroma = float(np.hypot(lab[1], lab[2]))
            score = 60000.0 + float(count) * (1.0 + (chroma / 10.0) ** 1.4)

            extracted.append({
                "hex": rgb_to_hex(srgb_val),
                "rgb": [int(c) for c in srgb_val],
                "type": "chromatic_mode",
                "pixel_weight": count,
                "variants_collapsed": 0,
                "recovered_opacities": [1.0],
                "_score": score,
                "_srgb": srgb_val
            })

        return extracted

    # ========================================================
    # COMPLETE PROCESSING PIPELINE
    # ========================================================

    def process_image(
        self,
        image_path: str,
        output_json_path: str
    ) -> Dict[str, Any]:

        bgr = cv2.imread(image_path)
        if bgr is None:
            raise FileNotFoundError(f"Could not open image: {image_path}")

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img_linear = srgb_to_linear(rgb)

        print(f"Loaded image: {image_path} ({rgb.shape[1]}x{rgb.shape[0]})")

        # 1. Superpixels
        labels, superpixels, adjacency = self.extract_superpixels(img_linear, rgb)

        # 2. Local Background Estimation
        swatches: List[ObservedSwatch] = []
        for sp_id, sp in superpixels.items():
            neighbor_ids = adjacency.get(sp_id, {})
            if not neighbor_ids:
                continue

            neighbor_infos = [
                SuperpixelInfo(
                    id=superpixels[n_id].id,
                    mean_rgb=superpixels[n_id].mean_rgb,
                    center_xy=superpixels[n_id].center_xy,
                    pixel_count=superpixels[n_id].pixel_count,
                    boundary_contact_len=contact_len
                )
                for n_id, contact_len in neighbor_ids.items()
            ]

            bg_color, strategy, confidence = self.bg_estimator.estimate_background(sp, neighbor_infos)
            swatches.append(ObservedSwatch(color=sp.mean_rgb, background=bg_color, pixel_count=sp.pixel_count))

        # 3. Latent Colors (RANSAC)
        resolved_families: List[ResolvedColorFamily] = self.candidate_engine.resolve_color_families(swatches)

        candidate_entries = []
        primary_detected_rgbs = []

        # A. Latent Colors
        for family in resolved_families:
            srgb_value = linear_to_srgb(family.true_color_rgb)
            total_weight = sum(s.pixel_count for s in family.explained_swatches)
            lab = rgb_to_lab(srgb_value)
            chroma = float(np.hypot(lab[1], lab[2]))
            score = 70000.0 + float(total_weight) * (1.0 + (chroma / 12.0))

            primary_detected_rgbs.append(srgb_value)
            candidate_entries.append({
                "hex": rgb_to_hex(srgb_value),
                "rgb": [int(c) for c in srgb_value],
                "type": "latent_underlying_color",
                "pixel_weight": int(total_weight),
                "variants_collapsed": len(family.explained_swatches),
                "recovered_opacities": [round(float(a), 3) for a in family.opacities],
                "_score": score,
                "_srgb": srgb_value
            })

        # B. Direct Chromatic Modes
        artistic_modes = self._extract_artistic_modes(rgb)
        for m in artistic_modes:
            primary_detected_rgbs.append(m["_srgb"])
        candidate_entries.extend(artistic_modes)

        # C. Harmonic Intermediate Tints & Deep Shades
        harmonic_modes = self._generate_harmonic_shades(primary_detected_rgbs[:10])
        candidate_entries.extend(harmonic_modes)

        # D. Micro-Superpixel Colors
        for swatch in swatches:
            srgb_value = linear_to_srgb(swatch.color)
            lab = rgb_to_lab(srgb_value)
            chroma = float(np.hypot(lab[1], lab[2]))
            score = float(swatch.pixel_count) * (1.0 + (chroma / 14.0))

            candidate_entries.append({
                "hex": rgb_to_hex(srgb_value),
                "rgb": [int(c) for c in srgb_value],
                "type": "unique_independent_color",
                "pixel_weight": int(swatch.pixel_count),
                "variants_collapsed": 0,
                "recovered_opacities": [1.0],
                "_score": score,
                "_srgb": srgb_value
            })

        # 4. Sort by Perceptual Salience
        candidate_entries.sort(key=lambda x: x["_score"], reverse=True)

        # 5. Fine-Grained Deduplication
        final_palette_entries = []
        max_allowed = self.target_palette_size

        for candidate in candidate_entries:
            cand_rgb = candidate["_srgb"]
            
            is_distinct = True
            for accepted in final_palette_entries:
                acc_rgb = accepted["_srgb"]
                if ciede2000_distance(cand_rgb, acc_rgb) < self.min_color_distance:
                    is_distinct = False
                    break

            if is_distinct:
                cleaned_entry = {k: v for k, v in candidate.items() if not k.startswith("_")}
                cleaned_entry["_srgb"] = cand_rgb
                final_palette_entries.append(cleaned_entry)

            if len(final_palette_entries) >= max_allowed:
                break

        for item in final_palette_entries:
            item.pop("_srgb", None)

        # 6. Save JSON
        palette_output = {
            "source_image": os.path.basename(image_path),
            "palette_size": len(final_palette_entries),
            "latent_families_resolved": len(resolved_families),
            "colors": final_palette_entries
        }

        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(palette_output, f, indent=2)

        print(f"Palette resolved with {len(final_palette_entries)} balanced tones -> {output_json_path}")
        return palette_output