import enum
import itertools

import attr


PNG_CHUNK_TYPE_PROPERTY_BITMASK = 0b00100000
PNG_CHUNK_TYPE_CODE_ALLOWED_BYTES = frozenset(
    itertools.chain(range(65, 91), range(97, 123)))


_valid_bytes = attr.validators.instance_of(bytes)


def _valid_chunk_type_code(instance, attribute, value):
    _valid_bytes(instance, attribute, value)
    if len(value) != 4:
        raise ValueError("{!r} must be exactly 4 bytes long".format(attribute))
    if not PNG_CHUNK_TYPE_CODE_ALLOWED_BYTES.issuperset(value):
        raise ValueError("{!r} contains invalid bytes".format(attribute))


@attr.attributes
class ChunkType:
    code = attr.attr(validator=_valid_chunk_type_code)

    @property
    def ancillary(self):
        # pylint: disable=unsubscriptable-object
        return bool(self.code[0] & PNG_CHUNK_TYPE_PROPERTY_BITMASK)

    @property
    def private(self):
        # pylint: disable=unsubscriptable-object
        return bool(self.code[1] & PNG_CHUNK_TYPE_PROPERTY_BITMASK)

    @property
    def reserved(self):
        # pylint: disable=unsubscriptable-object
        return bool(self.code[2] & PNG_CHUNK_TYPE_PROPERTY_BITMASK)

    @property
    def safe_to_copy(self):
        # pylint: disable=unsubscriptable-object
        return bool(self.code[3] & PNG_CHUNK_TYPE_PROPERTY_BITMASK)


# Standard PNG chunk names and type codes
# Names are taken from the headers of the PNG 1.2 spec in section 4.

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
CODE_TYPES = {
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


@attr.attributes
class ChunkHeadToken:
    """
    The start of a PNG chunk.

    :ivar length: The number of bytes comprising the chunk's data
    :type length: int
    :ivar code: The PNG chunk type code
    :type code: bytes
    :ivar position: Where the chunk started in the stream
    :type position: int
    """
    length = attr.attr()
    code = attr.attr()
    position = attr.attr()


@attr.attributes
class ChunkDataPartToken:
    """
    A portion (or all) of the data from a PNG chunk.

    :ivar head: The head token from this chunk
    :type head: :class:`ChunkHeadToken`
    :ivar data: The bytes from this portion of the chunk
    :type data: bytes
    """
    head = attr.attr()
    data = attr.attr()

    def __repr__(self):
        return '{name}(head={head!r}, data_length={length})'.format(
            name=self.__class__.__name__,
            head=self.head,
            length=len(self.data),
        )


@attr.attributes
class ChunkEndToken:
    """
    The end marker for a PNG chunk.

    :ivar head: The head token from this chunk
    :type head: :class:`ChunkHeadToken`
    :ivar crc32ok: If the CRC32 checksum validated properly
    :type crc32ok: bool
    """
    head = attr.attr()
    crc32ok = attr.attr()


class ImageHeaderColorType(enum.Enum):
    grayscale = 0
    rgb = 2
    palette = 3
    grayscale_alpha = 4
    rgb_alpha = 6


class CompressionMethod(enum.Enum):
    deflate32k = 0


class ImageHeaderFilterMethod(enum.Enum):
    adaptive_five_basic = 0


class ImageHeaderInterlaceMethod(enum.Enum):
    none = 0
    adam7 = 1
