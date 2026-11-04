import io
import tempfile
import os
from typing import Tuple, Literal
import numpy as np
from PIL import Image, UnidentifiedImageError
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.logging import logger
from app.utils.validators import get_file_extension, validate_file_extension, validate_file_size

NormalizationMethod = Literal["z_score", "min_max", "imagenet"]

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)


class MRIPreprocessor:
    """
    Preprocessing pipeline for Brain MRI scans.
    Handles decoding (2D images, DICOM, NIfTI), RGB conversion, resizing,
    intensity normalization, and tensor formatting (1, 3, H, W).
    """

    def __init__(
        self,
        target_size: Tuple[int, int] = (settings.IMAGE_INPUT_SIZE, settings.IMAGE_INPUT_SIZE),
        normalization: NormalizationMethod = "z_score",
    ) -> None:
        self.target_size = target_size
        self.normalization: NormalizationMethod = normalization

    def load_image_from_bytes(self, file_bytes: bytes, filename: str = "scan.png") -> Image.Image:
        """
        Decode raw bytes into a PIL Image.
        Supports standard raster images (.png, .jpg, .jpeg) as well as medical
        formats (.dcm, .nii, .nii.gz) when optional libraries are available.
        """
        validate_file_size(file_bytes)
        ext = validate_file_extension(filename) if filename else ".png"

        try:
            if ext == ".dcm":
                return self._load_dicom(file_bytes)
            if ext in (".nii", ".nii.gz"):
                return self._load_nifti(file_bytes, ext)

            image = Image.open(io.BytesIO(file_bytes))
            image.load()
            return image
        except HTTPException:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            logger.error(f"Failed to decode MRI scan '{filename}': {exc}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Corrupted or unreadable MRI image file: {filename}",
            ) from exc

    def _load_dicom(self, file_bytes: bytes) -> Image.Image:
        """Extract 2D slice from a DICOM (.dcm) payload."""
        try:
            import pydicom
        except ImportError as exc:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="pydicom is required to process DICOM (.dcm) files.",
            ) from exc

        dataset = pydicom.dcmread(io.BytesIO(file_bytes))
        pixel_array = dataset.pixel_array.astype(np.float32)
        if pixel_array.ndim > 2:
            mid_slice = pixel_array.shape[0] // 2
            pixel_array = pixel_array[mid_slice]
        scaled = self._scale_to_uint8(pixel_array)
        return Image.fromarray(scaled, mode="L")

    def _load_nifti(self, file_bytes: bytes, ext: str) -> Image.Image:
        """Extract central axial 2D slice from a 3D NIfTI (.nii / .nii.gz) volume."""
        try:
            import nibabel as nib
        except ImportError as exc:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="nibabel is required to process NIfTI (.nii) files.",
            ) from exc

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(file_bytes)
                temp_path = tmp.name

            volume = nib.load(temp_path).get_fdata().astype(np.float32)
            if volume.ndim >= 3:
                mid_slice = volume.shape[2] // 2
                slice_2d = volume[:, :, mid_slice]
            else:
                slice_2d = volume
            scaled = self._scale_to_uint8(slice_2d)
            return Image.fromarray(scaled, mode="L")
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    @staticmethod
    def _scale_to_uint8(array: np.ndarray) -> np.ndarray:
        """Rescale arbitrary float array into [0, 255] uint8 image space."""
        arr_min = float(np.min(array))
        arr_max = float(np.max(array))
        if arr_max - arr_min < 1e-8:
            return np.zeros(array.shape, dtype=np.uint8)
        normalized = (array - arr_min) / (arr_max - arr_min)
        return (normalized * 255.0).clip(0, 255).astype(np.uint8)

    def to_rgb(self, image: Image.Image) -> Image.Image:
        """Convert grayscale, palette, or RGBA MRI image to 3-channel RGB."""
        if image.mode != "RGB":
            return image.convert("RGB")
        return image

    def resize_image(self, image: Image.Image) -> Image.Image:
        """Resize PIL image to target model dimensions (default 224x224) using bilinear resampling."""
        if image.size == self.target_size:
            return image
        return image.resize(self.target_size, Image.Resampling.BILINEAR)

    def normalize_intensity(
        self,
        image_array: np.ndarray,
        method: NormalizationMethod | None = None,
    ) -> np.ndarray:
        """
        Normalize pixel intensity values of an image array.

        Args:
            image_array: Float32 array in [0, 255] or [0, 1].
            method: 'z_score' (zero mean, unit variance), 'min_max' ([0, 1]), or 'imagenet'.
        """
        norm_method = method or self.normalization
        arr = image_array.astype(np.float32)

        if norm_method == "min_max":
            arr_min = float(np.min(arr))
            arr_max = float(np.max(arr))
            if arr_max - arr_min < 1e-8:
                return np.zeros_like(arr, dtype=np.float32)
            return (arr - arr_min) / (arr_max - arr_min)

        if norm_method == "z_score":
            mean = float(np.mean(arr))
            std = float(np.std(arr))
            if std < 1e-8:
                return arr - mean
            return (arr - mean) / std

        if norm_method == "imagenet":
            # Expects channel-first (3, H, W) or channel-last (H, W, 3)
            scaled = arr / 255.0 if np.max(arr) > 1.0 else arr
            if scaled.ndim == 3 and scaled.shape[0] == 3:
                return (scaled - IMAGENET_MEAN) / IMAGENET_STD
            if scaled.ndim == 3 and scaled.shape[-1] == 3:
                mean_hwc = IMAGENET_MEAN.transpose(1, 2, 0)
                std_hwc = IMAGENET_STD.transpose(1, 2, 0)
                return (scaled - mean_hwc) / std_hwc
            raise ValueError("ImageNet normalization requires a 3-channel RGB array.")

        raise ValueError(f"Unsupported normalization method: {norm_method}")

    def to_tensor_format(self, rgb_array: np.ndarray) -> np.ndarray:
        """
        Convert an (H, W, 3) numpy array into batch-first NCHW tensor format (1, 3, H, W).
        """
        if rgb_array.ndim != 3 or rgb_array.shape[2] != 3:
            raise ValueError(
                f"Expected 3-channel (H, W, 3) array, got shape {rgb_array.shape}."
            )
        chw = np.transpose(rgb_array, (2, 0, 1))
        return np.expand_dims(chw, axis=0).astype(np.float32)

    def preprocess_bytes(
        self,
        file_bytes: bytes,
        filename: str = "scan.png",
        normalization: NormalizationMethod | None = None,
    ) -> Tuple[np.ndarray, Image.Image]:
        """
        Execute the full MRI preprocessing pipeline from raw uploaded bytes.

        Returns:
            Tuple of:
              - tensor: Preprocessed numpy tensor of shape (1, 3, 224, 224) and dtype float32.
              - rgb_resized: Resized 224x224 PIL RGB image (useful for Grad-CAM overlay).
        """
        raw_image = self.load_image_from_bytes(file_bytes, filename=filename)
        rgb_image = self.to_rgb(raw_image)
        rgb_resized = self.resize_image(rgb_image)

        img_array = np.asarray(rgb_resized, dtype=np.float32)
        normalized_array = self.normalize_intensity(img_array, method=normalization)
        tensor = self.to_tensor_format(normalized_array)

        logger.debug(
            f"Preprocessed '{filename}' -> tensor shape {tensor.shape}, "
            f"dtype={tensor.dtype}, norm={normalization or self.normalization}"
        )
        return tensor, rgb_resized


preprocessor = MRIPreprocessor()

