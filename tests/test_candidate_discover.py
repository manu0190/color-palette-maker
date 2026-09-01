import numpy as np

from backend.image_colors import ObservedSwatch
from backend.candidate_discovery import RobustCandidateEngine


def test_resolve_color_families_recovers_latent_color():
    # Ground-truth foreground color
    F_true = np.array(
        [220.0, 180.0, 40.0],
        dtype=np.float32,
    ) / 255.0

    # Different background contexts
    B1 = np.array(
        [80.0, 90.0, 100.0],
        dtype=np.float32,
    ) / 255.0

    B2 = np.array(
        [120.0, 130.0, 140.0],
        dtype=np.float32,
    ) / 255.0

    B3 = np.array(
        [60.0, 70.0, 80.0],
        dtype=np.float32,
    ) / 255.0

    # Known opacity values
    alpha1 = 0.25
    alpha2 = 0.55
    alpha3 = 0.85

    # Generate observed colors
    I1 = alpha1 * F_true + (1.0 - alpha1) * B1
    I2 = alpha2 * F_true + (1.0 - alpha2) * B2
    I3 = alpha3 * F_true + (1.0 - alpha3) * B3

    swatches = [
        ObservedSwatch(
            color=I1,
            background=B1,
            pixel_count=100,
        ),
        ObservedSwatch(
            color=I2,
            background=B2,
            pixel_count=100,
        ),
        ObservedSwatch(
            color=I3,
            background=B3,
            pixel_count=100,
        ),
    ]

    engine = RobustCandidateEngine(
        residual_thresh=0.04
    )

    resolved_families = engine.resolve_color_families(
        swatches
    )

    # At least one latent family should be discovered.
    assert len(resolved_families) >= 1

    # Find the family explaining the most observations.
    best_family = max(
        resolved_families,
        key=lambda family: len(family.explained_swatches),
    )

    # All three synthetic observations should belong
    # to the recovered family.
    assert len(best_family.explained_swatches) >= 3

    # Recovered latent color should be close to ground truth.
    np.testing.assert_allclose(
        best_family.true_color_rgb,
        F_true,
        atol=0.03,
    )

    # Residual should remain within a reasonable range.
    assert best_family.total_residual < 0.12

    # Three observations should produce three opacity values.
    assert len(best_family.opacities) == 3