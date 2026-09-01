import cv2
import numpy as np

from dataclasses import dataclass
from typing import List, Optional, Tuple


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class SuperpixelInfo:
    """
    Information about one SLIC superpixel.

    All RGB values used by the main pipeline are expected
    to be normalized linear RGB values in the range [0, 1].
    """

    id: int
    mean_rgb: np.ndarray
    center_xy: np.ndarray
    pixel_count: int
    boundary_contact_len: int = 0


@dataclass
class ObservedSwatch:
    """
    One observed color together with its estimated background.

    color:
        Observed color I, normalized linear RGB [0, 1].

    background:
        Estimated background B, normalized linear RGB [0, 1].
    """

    color: np.ndarray
    background: np.ndarray
    pixel_count: int


@dataclass
class ResolvedColor:
    """
    Result of validating a candidate foreground color F.
    """

    true_color_rgb: np.ndarray
    is_latent_source: bool
    explained_swatches: List[ObservedSwatch]
    opacities: List[float]


# ============================================================
# LOCAL BACKGROUND ESTIMATOR
# ============================================================

class LocalBackgroundEstimator:

    def __init__(
        self,
        continuity_dist_thresh: float = 0.10,
        cluster_merge_thresh: float = 0.08
    ):
        self.continuity_thresh = continuity_dist_thresh
        self.cluster_thresh = cluster_merge_thresh

    # ========================================================
    # ESTIMATE LOCAL BACKGROUND
    # ========================================================

    def estimate_background(
        self,
        target: SuperpixelInfo,
        neighbors: List[SuperpixelInfo]
    ) -> Tuple[np.ndarray, str, float]:

        # ----------------------------------------------------
        # No neighbors
        # ----------------------------------------------------

        if not neighbors:
            return (
                target.mean_rgb.copy(),
                "self_fallback",
                0.0
            )

        # ----------------------------------------------------
        # Only one neighbor
        # ----------------------------------------------------

        if len(neighbors) == 1:
            return (
                neighbors[0].mean_rgb.copy(),
                "single_neighbor",
                0.5
            )

        # ====================================================
        # STRATEGY 1
        #
        # Opposite Continuous Pair
        # ====================================================

        opposite_candidates = []

        for i in range(len(neighbors)):

            for j in range(i + 1, len(neighbors)):

                nA = neighbors[i]
                nB = neighbors[j]

                # ------------------------------------------------
                # Spatial vectors
                # ------------------------------------------------

                vec_A = (
                    nA.center_xy
                    - target.center_xy
                )

                vec_B = (
                    nB.center_xy
                    - target.center_xy
                )

                norm_A = np.linalg.norm(vec_A)
                norm_B = np.linalg.norm(vec_B)

                if norm_A < 1e-6 or norm_B < 1e-6:
                    continue

                # ------------------------------------------------
                # Angle between neighbors
                # ------------------------------------------------

                cos_angle = (
                    np.dot(vec_A, vec_B)
                    / (norm_A * norm_B)
                )

                # Roughly opposite directions
                #
                # cos(120 degrees) = -0.5
                #

                if cos_angle < -0.5:

                    color_diff = np.linalg.norm(
                        nA.mean_rgb
                        - nB.mean_rgb
                    )

                    # Colors should be reasonably continuous
                    if color_diff < self.continuity_thresh:

                        total_weight = (
                            nA.boundary_contact_len
                            + nB.boundary_contact_len
                        )

                        # Avoid division by zero
                        if total_weight <= 0:
                            total_weight = 1

                        # Boundary-weighted average
                        avg_bg = (
                            nA.mean_rgb
                            * nA.boundary_contact_len
                            +
                            nB.mean_rgb
                            * nB.boundary_contact_len
                        ) / total_weight

                        confidence = (
                            1.0
                            -
                            color_diff
                            / self.continuity_thresh
                        )

                        opposite_candidates.append(
                            (
                                avg_bg,
                                confidence,
                                total_weight
                            )
                        )

        # ----------------------------------------------------
        # Select best opposite pair
        # ----------------------------------------------------

        if opposite_candidates:

            opposite_candidates.sort(
                key=lambda x: (
                    x[1],
                    x[2]
                ),
                reverse=True
            )

            best_bg, confidence, _ = (
                opposite_candidates[0]
            )

            return (
                best_bg.astype(np.float32),
                "continuous_opposite_pair",
                float(confidence)
            )

        # ====================================================
        # STRATEGY 2
        #
        # Dominant Boundary Contact Color Cluster
        # ====================================================

        clusters = []

        for neighbor in neighbors:

            placed = False

            for cluster in clusters:

                distance = np.linalg.norm(
                    neighbor.mean_rgb
                    - cluster["mean_rgb"]
                )

                if distance < self.cluster_thresh:

                    old_contact = (
                        cluster["contact"]
                    )

                    new_contact = (
                        old_contact
                        + neighbor.boundary_contact_len
                    )

                    # Avoid zero division
                    if new_contact <= 0:
                        new_contact = 1

                    cluster["mean_rgb"] = (
                        cluster["mean_rgb"]
                        * old_contact
                        +
                        neighbor.mean_rgb
                        * neighbor.boundary_contact_len
                    ) / new_contact

                    cluster["contact"] = new_contact

                    cluster["members"].append(
                        neighbor
                    )

                    placed = True
                    break

            # ------------------------------------------------
            # Create a new cluster
            # ------------------------------------------------

            if not placed:

                clusters.append(
                    {
                        "mean_rgb":
                            neighbor.mean_rgb.copy(),

                        "contact":
                            neighbor.boundary_contact_len,

                        "members":
                            [neighbor]
                    }
                )

        # ----------------------------------------------------
        # Safety fallback
        # ----------------------------------------------------

        if not clusters:
            return (
                target.mean_rgb.copy(),
                "self_fallback",
                0.0
            )

        # ----------------------------------------------------
        # Select dominant cluster
        # ----------------------------------------------------

        clusters.sort(
            key=lambda c: c["contact"],
            reverse=True
        )

        dominant_cluster = clusters[0]

        total_boundary = sum(
            n.boundary_contact_len
            for n in neighbors
        )

        confidence = (
            dominant_cluster["contact"]
            /
            max(
                1,
                total_boundary
            )
        )

        return (
            dominant_cluster["mean_rgb"].astype(
                np.float32
            ),
            "dominant_contact_cluster",
            float(confidence)
        )


# ============================================================
# OPACITY VALIDATOR
# ============================================================

class ColorFoundryV1Validator:

    def __init__(
        self,
        residual_thresh: float = 0.04
    ):
        """
        residual_thresh is measured in normalized linear RGB.

        Example:
            0.04 means maximum Euclidean RGB reconstruction
            error of 0.04 in normalized linear RGB space.
        """

        self.residual_thresh = residual_thresh

    # ========================================================
    # TEST ALPHA HYPOTHESIS
    # ========================================================

    def test_alpha_hypothesis(
        self,
        candidate_F: np.ndarray,
        swatches: List[ObservedSwatch]
    ) -> Optional[ResolvedColor]:

        explained = []
        opacities = []

        candidate_F = np.asarray(
            candidate_F,
            dtype=np.float32
        )

        for swatch in swatches:

            I = np.asarray(
                swatch.color,
                dtype=np.float32
            )

            B = np.asarray(
                swatch.background,
                dtype=np.float32
            )

            # ------------------------------------------------
            # Foreground-background direction
            # ------------------------------------------------

            vec_fb = candidate_F - B

            denom = np.dot(
                vec_fb,
                vec_fb
            )

            if denom < 1e-8:
                continue

            # ------------------------------------------------
            # Estimate alpha
            #
            # I = alpha*F + (1-alpha)*B
            #
            # Therefore:
            #
            # alpha =
            # ((I-B) dot (F-B))
            # -------------------
            # ||F-B||²
            # ------------------------------------------------

            alpha = np.dot(
                I - B,
                vec_fb
            ) / denom

            # ------------------------------------------------
            # Physically plausible alpha
            #
            # Small tolerance around [0,1] allows numerical
            # noise.
            # ------------------------------------------------

            if not (
                0.20 <= alpha <= 1.05
            ):
                continue

            alpha_clamped = np.clip(
                alpha,
                0.0,
                1.0
            )

            # ------------------------------------------------
            # Reconstruct observed color
            # ------------------------------------------------

            reconstructed_I = (
                alpha_clamped
                * candidate_F
                +
                (1.0 - alpha_clamped)
                * B
            )

            # ------------------------------------------------
            # Reconstruction error
            # ------------------------------------------------

            residual = np.linalg.norm(
                I - reconstructed_I
            )

            # ------------------------------------------------
            # Validate
            # ------------------------------------------------

            if residual <= self.residual_thresh:

                explained.append(
                    swatch
                )

                opacities.append(
                    float(alpha_clamped)
                )

        # ----------------------------------------------------
        # Require at least two observations.
        #
        # One observation is not enough to confidently claim
        # a latent underlying color.
        # ----------------------------------------------------

        if len(explained) >= 3:

            return ResolvedColor(
                true_color_rgb=candidate_F,
                is_latent_source=True,
                explained_swatches=explained,
                opacities=opacities
            )

        return None


# ============================================================
# BACKWARD-COMPATIBILITY ALIAS
# ============================================================
#
# Older experimental code used the name "Superpixel".
# Keeping this alias means those scripts won't immediately
# break if they still import Superpixel.
#

Superpixel = SuperpixelInfo