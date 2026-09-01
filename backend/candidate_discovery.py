import numpy as np
from typing import List, Optional
from dataclasses import dataclass
import random

from backend.image_colors import ObservedSwatch

@dataclass
class ResolvedColorFamily:
    true_color_rgb: np.ndarray
    explained_swatches: List[ObservedSwatch]
    opacities: List[float]
    total_residual: float

class RobustCandidateEngine:
    def __init__(
        self,
        residual_thresh: float = 0.05,     # Inlier residual threshold (~12/255)
        min_contrast: float = 0.025,       # Minimum ||I - B|| to consider
        ransac_iterations: int = 250,      # RANSAC trials per extraction loop
        min_inliers: int = 2               # Minimum swatches to form a valid family
    ):
        self.residual_thresh = residual_thresh
        self.min_contrast = min_contrast
        self.ransac_iterations = ransac_iterations
        self.min_inliers = min_inliers

    def _intersect_two_rays(self, s1: ObservedSwatch, s2: ObservedSwatch) -> Optional[np.ndarray]:
        """Calculates the closest point of approach between two 3D rays."""
        d1 = (s1.color - s1.background).astype(np.float64)
        d2 = (s2.color - s2.background).astype(np.float64)
        
        len1, len2 = np.linalg.norm(d1), np.linalg.norm(d2)
        if len1 < self.min_contrast or len2 < self.min_contrast:
            return None

        u1, u2 = d1 / len1, d2 / len2
        w0 = (s1.background - s2.background).astype(np.float64)

        a = np.dot(u1, u1)  # 1.0
        b = np.dot(u1, u2)
        c = np.dot(u2, u2)  # 1.0
        d_val = np.dot(u1, w0)
        e_val = np.dot(u2, w0)

        denom = a * c - b * b
        if abs(denom) < 1e-4:  # Parallel or collinear rays
            return None

        s = (b * e_val - c * d_val) / denom
        t = (a * e_val - b * d_val) / denom

        # Rays must point forward towards higher opacity
        if s < 0 or t < 0:
            return None

        pt1 = s1.background + s * u1
        pt2 = s2.background + t * u2

        # Rays must pass close to each other in 3D color space
        if np.linalg.norm(pt1 - pt2) > (self.residual_thresh * 2.0):
            return None

        midpoint = (pt1 + pt2) / 2.0
        if np.all(midpoint >= -0.05) and np.all(midpoint <= 1.05):
            return np.clip(midpoint.astype(np.float32), 0.0, 1.0)
        return None

    def _refine_least_squares(self, inliers: List[ObservedSwatch]) -> Optional[np.ndarray]:
        """Refines F across all current inliers using multi-ray projection least-squares."""
        A = np.zeros((3, 3), dtype=np.float64)
        b = np.zeros(3, dtype=np.float64)
        I3 = np.eye(3, dtype=np.float64)

        for s in inliers:
            d = (s.color - s.background).astype(np.float64)
            u = d / np.linalg.norm(d)
            P = I3 - np.outer(u, u)
            A += P
            b += P @ s.background.astype(np.float64)

        if np.linalg.cond(A) > 1e4:
            return None

        try:
            F = np.linalg.solve(A, b)
            if np.all(F >= -0.05) and np.all(F <= 1.05):
                return np.clip(F.astype(np.float32), 0.0, 1.0)
        except np.linalg.LinAlgError:
            pass
        return None

    def _get_inliers_for_f(self, F: np.ndarray, pool: List[ObservedSwatch]):
        """Finds all swatches that fit the alpha blending equation for a candidate F."""
        inliers = []
        opacities = []
        errors = []

        for s in pool:
            vec_fb = F - s.background
            denom = np.dot(vec_fb, vec_fb)
            if denom < 1e-6:
                continue

            alpha = np.dot(s.color - s.background, vec_fb) / denom
            if 0.05 <= alpha <= 1.05:
                alpha_clamped = float(np.clip(alpha, 0.0, 1.0))
                reconstructed = alpha_clamped * F + (1.0 - alpha_clamped) * s.background
                err = float(np.linalg.norm(s.color - reconstructed))

                if err <= self.residual_thresh:
                    inliers.append(s)
                    opacities.append(alpha_clamped)
                    errors.append(err)

        return inliers, opacities, errors

    def resolve_color_families(
        self,
        swatches: List[ObservedSwatch]
    ) -> List[ResolvedColorFamily]:
        valid_pool = [
            s for s in swatches 
            if np.linalg.norm(s.color - s.background) >= self.min_contrast
        ]

        if len(valid_pool) < self.min_inliers:
            return []

        unclaimed = list(valid_pool)
        discovered_families: List[ResolvedColorFamily] = []

        # Safety cap on iterations to prevent runaway loops
        max_loops = len(valid_pool)
        loop_count = 0

        while len(unclaimed) >= self.min_inliers and loop_count < max_loops:
            loop_count += 1
            best_F = None
            best_inliers = []
            best_opacities = []
            best_errors = []

            # --- RANSAC Sampling ---
            for _ in range(self.ransac_iterations):
                if len(unclaimed) < 2:
                    break

                s1, s2 = random.sample(unclaimed, 2)
                cand_F = self._intersect_two_rays(s1, s2)
                if cand_F is None:
                    continue

                inliers, opacities, errors = self._get_inliers_for_f(cand_F, unclaimed)

                if len(inliers) > len(best_inliers) or (
                    len(inliers) == len(best_inliers) and sum(errors) < sum(best_errors)
                ):
                    best_F = cand_F
                    best_inliers = inliers
                    best_opacities = opacities
                    best_errors = errors

            # Must have at least min_inliers from the random search
            if best_F is None or len(best_inliers) < self.min_inliers:
                break

            # --- Least-Squares Refinement ---
            refined_F = self._refine_least_squares(best_inliers)
            if refined_F is not None:
                ref_inliers, ref_opacities, ref_errors = self._get_inliers_for_f(refined_F, unclaimed)
                # Only accept refinement if it retains sufficient inliers
                if len(ref_inliers) >= self.min_inliers:
                    best_F = refined_F
                    best_inliers = ref_inliers
                    best_opacities = ref_opacities
                    best_errors = ref_errors

            # Final guard: Do not create a family if inliers dropped below threshold
            if len(best_inliers) < self.min_inliers:
                break

            total_res = float(np.sqrt(np.sum(np.square(best_errors)))) if best_errors else 0.0

            discovered_families.append(ResolvedColorFamily(
                true_color_rgb=best_F,
                explained_swatches=best_inliers,
                opacities=best_opacities,
                total_residual=total_res
            ))

            # Remove claimed inliers so unclaimed strictly decreases
            unclaimed = [s for s in unclaimed if not any(s is inlier for inlier in best_inliers)]

        return discovered_families