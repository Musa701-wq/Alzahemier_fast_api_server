import io
import numpy as np
import pytest
from PIL import Image
from fastapi import HTTPException

from app.utils.validators import (
    get_file_extension,
    validate_file_extension,
    validate_file_size,
)
from app.services.preprocessor import MRIPreprocessor, preprocessor


def _create_test_image_bytes(
    mode: str = "L",
    size: tuple[int, int] = (128, 160),
    fmt: str = "PNG",
) -> bytes:
    """Create a synthetic grayscale or RGB image in memory for testing."""
    rng = np.random.default_rng(seed=42)
    if mode == "L":
        arr = rng.integers(10, 245, size=(size[1], size[0]), dtype=np.uint8)
    elif mode == "RGB":
        arr = rng.integers(10, 245, size=(size[1], size[0], 3), dtype=np.uint8)
    elif mode == "RGBA":
        arr = rng.integers(10, 245, size=(size[1], size[0], 4), dtype=np.uint8)
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    img = Image.fromarray(arr, mode=mode)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


class TestMRIValidators:
    """Unit tests for MRI file extension and size validators."""

    @pytest.mark.parametrize(
        "filename,expected_ext",
        [
            ("brain_scan.png", ".png"),
            ("MRI_SLICE.JPG", ".jpg"),
            ("subject_01.jpeg", ".jpeg"),
            ("dicom_slice.dcm", ".dcm"),
            ("volume.nii", ".nii"),
            ("volume_compressed.nii.gz", ".nii.gz"),
        ],
    )
    def test_valid_file_extensions(self, filename: str, expected_ext: str):
        assert get_file_extension(filename) == expected_ext
        assert validate_file_extension(filename) == expected_ext

    @pytest.mark.parametrize(
        "invalid_filename",
        [
            "",
            "   ",
            "document.pdf",
            "archive.zip",
            "executable.exe",
            "no_extension",
        ],
    )
    def test_invalid_file_extensions_raise_400(self, invalid_filename: str):
        with pytest.raises(HTTPException) as exc_info:
            validate_file_extension(invalid_filename)
        assert exc_info.value.status_code == 400

    def test_validate_file_size_valid(self):
        payload = b"x" * (1024 * 512)  # 512 KB
        assert validate_file_size(payload, max_size_mb=25) == len(payload)

    def test_validate_file_size_empty_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_file_size(b"")
        assert exc_info.value.status_code == 400

    def test_validate_file_size_exceeds_limit_raises_413(self):
        oversized = b"x" * (2 * 1024 * 1024 + 1)  # > 2 MB
        with pytest.raises(HTTPException) as exc_info:
            validate_file_size(oversized, max_size_mb=2)
        assert exc_info.value.status_code == 413


class TestMRIPreprocessor:
    """Unit tests for MRI image resizing, RGB conversion, normalization, and tensor formatting."""

    def test_grayscale_to_rgb_and_resize(self):
        img_bytes = _create_test_image_bytes(mode="L", size=(300, 180), fmt="PNG")
        loaded = preprocessor.load_image_from_bytes(img_bytes, filename="axial_slice.png")
        assert loaded.mode == "L"

        rgb_img = preprocessor.to_rgb(loaded)
        assert rgb_img.mode == "RGB"

        resized_img = preprocessor.resize_image(rgb_img)
        assert resized_img.size == (224, 224)

    def test_z_score_normalization_statistics(self):
        rng = np.random.default_rng(123)
        sample = rng.uniform(20.0, 220.0, size=(224, 224, 3)).astype(np.float32)

        normed = preprocessor.normalize_intensity(sample, method="z_score")
        assert normed.dtype == np.float32
        assert np.isclose(np.mean(normed), 0.0, atol=1e-5)
        assert np.isclose(np.std(normed), 1.0, atol=1e-5)

    def test_min_max_normalization_bounds(self):
        sample = np.array([[[10.0, 50.0, 210.0], [30.0, 90.0, 150.0]]], dtype=np.float32)
        normed = preprocessor.normalize_intensity(sample, method="min_max")
        assert np.isclose(np.min(normed), 0.0, atol=1e-6)
        assert np.isclose(np.max(normed), 1.0, atol=1e-6)

    def test_tensor_formatting_shape(self):
        dummy_hwc = np.zeros((224, 224, 3), dtype=np.float32)
        tensor = preprocessor.to_tensor_format(dummy_hwc)
        assert tensor.shape == (1, 3, 224, 224)
        assert tensor.dtype == np.float32

    def test_full_preprocess_bytes_pipeline_grayscale_and_rgba(self):
        for mode in ("L", "RGB", "RGBA"):
            img_bytes = _create_test_image_bytes(mode=mode, size=(256, 256), fmt="PNG")
            tensor, pil_resized = preprocessor.preprocess_bytes(
                img_bytes,
                filename=f"mri_{mode.lower()}.png",
                normalization="z_score",
            )
            assert tensor.shape == (1, 3, 224, 224)
            assert tensor.dtype == np.float32
            assert pil_resized.size == (224, 224)
            assert pil_resized.mode == "RGB"

    def test_corrupted_image_bytes_raises_400(self):
        corrupted_bytes = b"not_a_valid_image_file_content"
        with pytest.raises(HTTPException) as exc_info:
            preprocessor.preprocess_bytes(corrupted_bytes, filename="corrupted.png")
        assert exc_info.value.status_code == 400

