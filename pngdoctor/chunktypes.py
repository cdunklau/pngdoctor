"""
Standard PNG chunk names and type codes

Names are taken from the headers of the PNG 1.2 spec in section 4.
"""
from pngdoctor.models import ChunkType


# Critical chunks
IMAGE_HEADER = ChunkType(b'IHDR')
PALETTE = ChunkType(b'PLTE')
IMAGE_DATA = ChunkType(b'IDAT')
IMAGE_TRAILER = ChunkType(b'IEND')

# Ancillary chunks
TRANSPARENCY = ChunkType(b'tRNS')
# Color space information
IMAGE_GAMMA = ChunkType(b'gAMA')
PRIMARY_CHROMATICITIES = ChunkType(b'cHRM')
STANDARD_RGB_COLOR_SPACE = ChunkType(b'sRGB')
EMBEDDED_ICC_PROFILE = ChunkType(b'iCCP')

# Textual information
TEXTUAL_DATA = ChunkType(b'tEXt')
COMPRESSED_TEXTUAL_DATA = ChunkType(b'zTXt')
INTERNATIONAL_TEXTUAL_DATA = ChunkType(b'iTXt')

# Miscellaneous information
BACKGROUND_COLOR = ChunkType(b'bKGD')
PHYSICAL_PIXEL_DIMENSIONS = ChunkType(b'pHYs')
SIGNIFICANT_BITS = ChunkType(b'sBIT')
SUGGESTED_PALETTE = ChunkType(b'sPLT')
PALETTE_HISTOGRAM = ChunkType(b'hIST')
IMAGE_LAST_MODIFICATION_TIME = ChunkType(b'tIME')

# Map of chunk type codes (bytes) to their ChunkType instances
CODE_TO_CHUNK_TYPE = {
    IMAGE_HEADER.code: IMAGE_HEADER,
    PALETTE.code: PALETTE,
    IMAGE_DATA.code: IMAGE_DATA,
    IMAGE_TRAILER.code: IMAGE_TRAILER,
    TRANSPARENCY.code: TRANSPARENCY,
    IMAGE_GAMMA.code: IMAGE_GAMMA,
    PRIMARY_CHROMATICITIES.code: PRIMARY_CHROMATICITIES,
    STANDARD_RGB_COLOR_SPACE.code: STANDARD_RGB_COLOR_SPACE,
    EMBEDDED_ICC_PROFILE.code: EMBEDDED_ICC_PROFILE,
    TEXTUAL_DATA.code: TEXTUAL_DATA,
    COMPRESSED_TEXTUAL_DATA.code: COMPRESSED_TEXTUAL_DATA,
    INTERNATIONAL_TEXTUAL_DATA.code: INTERNATIONAL_TEXTUAL_DATA,
    BACKGROUND_COLOR.code: BACKGROUND_COLOR,
    PHYSICAL_PIXEL_DIMENSIONS.code: PHYSICAL_PIXEL_DIMENSIONS,
    SIGNIFICANT_BITS.code: SIGNIFICANT_BITS,
    SUGGESTED_PALETTE.code: SUGGESTED_PALETTE,
    PALETTE_HISTOGRAM.code: PALETTE_HISTOGRAM,
    IMAGE_LAST_MODIFICATION_TIME.code: IMAGE_LAST_MODIFICATION_TIME,
}
