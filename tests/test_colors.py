import numpy as np

from backend.image_colors import (
    ColorFoundryV1Validator,
    ObservedSwatch,
)


def test_alpha_hypothesis_recovers_color():
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

    validator = ColorFoundryV1Validator(
        residual_thresh=0.04
    )

    result = validator.test_alpha_hypothesis(
        candidate_F=F_true,
        swatches=swatches,
    )

    # The hypothesis should be valid.
    assert result is not None

    # Recovered color should be close to the known color.
    np.testing.assert_allclose(
        result.true_color_rgb,
        F_true,
        atol=0.01,
    )

    # Three observations should produce three opacity values.
    assert len(result.opacities) == 3

    # Recovered opacities should be close to ground truth.
    np.testing.assert_allclose(
        result.opacities,
        [alpha1, alpha2, alpha3],
        atol=0.01,
    )