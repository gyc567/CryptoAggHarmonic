"""Chart compression and size control."""

import logging

from app.domain.schemas import ChartMeta

logger = logging.getLogger(__name__)

# Web-optimized defaults
DEFAULT_DPI = 150
MAX_DPI = 200
MIN_DPI = 100

DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 800
MAX_WIDTH = 1600
MAX_HEIGHT = 1200


def compress_chart(
    image_bytes: bytes,
    target_dpi: int = DEFAULT_DPI,
    max_width: int = DEFAULT_WIDTH,
    max_height: int = DEFAULT_HEIGHT,
    quality: int = 85,
) -> tuple[bytes, ChartMeta]:
    """Compress chart image bytes for web delivery.

    Args:
        image_bytes: Raw PNG image bytes.
        target_dpi: Target DPI (clamped to MIN_DPI..MAX_DPI).
        max_width: Maximum width in pixels.
        max_height: Maximum height in pixels.
        quality: PNG compression quality hint (not directly applicable to PNG,
            but used if converting to other formats).

    Returns:
        Tuple of (compressed_bytes, ChartMeta).
    """
    dpi = max(MIN_DPI, min(target_dpi, MAX_DPI))

    # For PNG, we rely on DPI reduction at generation time.
    # This function primarily validates and returns metadata.
    # If PIL is available, we could resize; for now, just validate.
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        orig_width, orig_height = img.size

        # Resize if exceeding max dimensions
        if orig_width > max_width or orig_height > max_height:
            ratio = min(max_width / orig_width, max_height / orig_height)
            new_width = int(orig_width * ratio)
            new_height = int(orig_height * ratio)
            img = img.resize((new_width, new_height), Image.LANCZOS)

            output = io.BytesIO()
            img.save(output, format="PNG", optimize=True)
            compressed = output.getvalue()
            final_width, final_height = img.size
        else:
            compressed = image_bytes
            final_width, final_height = orig_width, orig_height

        meta = ChartMeta(
            format="png",
            width=final_width,
            height=final_height,
            path=None,
            url=None,
        )
        return compressed, meta

    except ImportError:
        # PIL not available, pass through with estimated metadata
        logger.warning("PIL not available, skipping chart compression")
        meta = ChartMeta(
            format="png",
            width=min(int(dpi * 8), max_width),
            height=min(int(dpi * 6), max_height),
            path=None,
            url=None,
        )
        return image_bytes, meta


def estimate_size(image_bytes: bytes) -> int:
    """Estimate image size in bytes.

    Args:
        image_bytes: Image bytes.

    Returns:
        Size in bytes.
    """
    return len(image_bytes)


def validate_chart_size(image_bytes: bytes, max_size_bytes: int = 1_048_576) -> bool:
    """Check if chart size is within limit.

    Args:
        image_bytes: Image bytes.
        max_size_bytes: Maximum allowed size (default 1MB).

    Returns:
        True if within limit, False otherwise.
    """
    return len(image_bytes) <= max_size_bytes
