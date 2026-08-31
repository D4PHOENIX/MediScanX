"""Tests for the Skin Lesion Inference Service engine and preprocessor."""

import pytest

def test_preprocessor_corrupt_image(tmp_path) -> None:
    """Assert preprocessor raises UnreadableImageFormatError on corrupt image."""
    from app.engine.preprocessor import SkinPreprocessor
    from app.core.config import SkinInferenceConfig
    from app.core.exceptions import UnreadableImageFormatError
    
    cfg = SkinInferenceConfig()
    preprocessor = SkinPreprocessor(cfg)
    
    corrupt_image = tmp_path / "corrupt.jpg"
    corrupt_image.write_bytes(b"not an image")
    
    with pytest.raises(UnreadableImageFormatError):
        preprocessor.process(str(corrupt_image))
