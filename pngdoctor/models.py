import abc
import enum
import itertools
import struct
from collections import namedtuple

from pngdoctor.exceptions import PNGSyntaxError


PNG_CHUNK_TYPE_PROPERTY_BITMASK = 0b00100000
PNG_CHUNK_TYPE_CODE_ALLOWED_BYTES = frozenset(
    itertools.chain(range(65, 91), range(97, 123)))


class PNGChunkType(namedtuple('_ChunkType', ['code'])):
    def __new__(cls, code):
        if not isinstance(code, bytes):
            raise TypeError("Argument 'code' must be bytes")
        if len(code) != 4:
            raise ValueError("'code' must be exactly 4 bytes long")
        if not PNG_CHUNK_TYPE_CODE_ALLOWED_BYTES.issuperset(code):
            raise ValueError("'code' contains invalid bytes")
        return super(PNGChunkType, cls).__new__(cls, code)

    @property
    def ancillary(self):
        return bool(self.code[0] & PNG_CHUNK_TYPE_PROPERTY_BITMASK)

    @property
    def private(self):
        return bool(self.code[1] & PNG_CHUNK_TYPE_PROPERTY_BITMASK)

    @property
    def reserved(self):
        return bool(self.code[2] & PNG_CHUNK_TYPE_PROPERTY_BITMASK)

    @property
    def safe_to_copy(self):
        return bool(self.code[3] & PNG_CHUNK_TYPE_PROPERTY_BITMASK)


# Standard PNG chunk names and type codes
# Names are taken from the headers of the PNG 1.2 spec in section 4.

## Critical chunks
IMAGE_HEADER = PNGChunkType(b'IHDR')
PALETTE = PNGChunkType(b'PLTE')
IMAGE_DATA = PNGChunkType(b'IDAT')
IMAGE_TRAILER = PNGChunkType(b'IEND')

## Ancillary chunks
TRANSPARENCY = PNGChunkType(b'tRNS')
# Color space information
IMAGE_GAMMA = PNGChunkType(b'gAMA')
PRIMARY_CHROMATICITIES = PNGChunkType(b'cHRM')
STANDARD_RGB_COLOR_SPACE = PNGChunkType(b'sRGB')
EMBEDDED_ICC_PROFILE = PNGChunkType(b'iCCP')

# Textual information
TEXTUAL_DATA = PNGChunkType(b'tEXt')
COMPRESSED_TEXTUAL_DATA = PNGChunkType(b'zTXt')
INTERNATIONAL_TEXTUAL_DATA = PNGChunkType(b'iTXt')

# Miscellaneous information
BACKGROUND_COLOR = PNGChunkType(b'bKGD')
PHYSICAL_PIXEL_DIMENSIONS = PNGChunkType(b'pHYs')
SIGNIFICANT_BITS = PNGChunkType(b'sBIT')
SUGGESTED_PALETTE = PNGChunkType(b'sPLT')
PALETTE_HISTOGRAM = PNGChunkType(b'hIST')
IMAGE_LAST_MODIFICATION_TIME = PNGChunkType(b'tIME')

# Map of chunk type codes (bytes) to their PNGChunkType instances
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



PNG_MAX_HEIGHT = PNG_MAX_WIDTH = 2**31 - 1
PNG_MIN_WIDTH = PNG_MIN_HEIGHT = 1


PNG_CHUNK_DATA_NOT_SET = object()


class AbstractPNGChunk(metaclass=abc.ABCMeta):
    def __init__(self, chunk_data, ihdr):
        """
        If the IHDR chunk has been seen, ``ihdr`` will be an instance
        of `PNGChunkIHDR`, otherwise ``None``.
        """
        self.chunk_data = chunk_data
        self.ihdr = ihdr

    @property
    def data_length(self):
        return len(self.chunk_data)

    @abc.abstractproperty
    def chunk_type(self):
        """
        The chunk type, an instance of `PNGChunkType`

        This should be treated as read-only.
        """

    @abc.abstractmethod
    def parse(self):
        """
        Parse the chunk data and set the results as attributes.

        Raise PNGSyntaxError if there was a problem parsing the data.
        """

    @abc.abstractmethod
    def repr_contents(self):
        """
        Return a string that will be included in the __repr__ output.
        """

    def __repr__(self):
        return '<{classname} {contents}>'.format(
            classname=self.__class__.__name__,
            contents=self.repr_contents()
        )


# Map of chunk type code -> chunk class
chunk_registry = {}


def chunk(cls):
    code = cls.chunk_type.code
    if code in chunk_registry:
        raise RuntimeError("Chunk with code {code} already registered".format(
            code=code
        ))
    chunk_registry[code] = cls
    return cls


class UnknownPNGChunk(AbstractPNGChunk):
    chunk_type = None

    def parse(self):
        pass

    def repr_contents(self):
        return ''


### Critical Chunks

# Fields are width, height, bit depth, color type, compression method,
# filter method, and interlace method
IHDR_FIELD_STRUCT = struct.Struct('>IIBBBBB')
# Field definitions
IHDR_ALLOWED_BIT_DEPTHS = set([1, 2, 4, 8, 16])


class IHDRColorType(enum.Enum):
    grayscale = 0
    rgb = 2
    palette = 3
    grayscale_alpha = 4
    rgb_alpha = 6

    def allows_bit_depth(self, bit_depth):
        return bit_depth in IHDRColorTypeAllowedBitDepth[self.name].value


class IHDRColorTypeAllowedBitDepth(enum.Enum):
    grayscale = frozenset([1, 2, 4, 8, 16])
    rgb = frozenset([8, 16])
    palette = frozenset([1, 2, 4, 8])
    grayscale_alpha = frozenset([8, 16])
    rgb_alpha = frozenset([8, 16])


class IHDRCompressionMethod(enum.Enum):
    deflate32k = 0


class IHDRFilterMethod(enum.Enum):
    adaptive_five_basic = 0


class IHDRInterlaceMethod(enum.Enum):
    none = 0
    adam7 = 1


@chunk
class ImageHeaderPNGChunk(AbstractPNGChunk):
    chunk_type = PNGChunkType(b'IHDR')

    width = PNG_CHUNK_DATA_NOT_SET
    height = PNG_CHUNK_DATA_NOT_SET
    bit_depth = PNG_CHUNK_DATA_NOT_SET
    color_type = PNG_CHUNK_DATA_NOT_SET
    compression_method = PNG_CHUNK_DATA_NOT_SET
    filter_method = PNG_CHUNK_DATA_NOT_SET
    interlace_method = PNG_CHUNK_DATA_NOT_SET

    def parse(self):
        self._validate_length()
        (
            width, height, bit_depth, color_type, compression_method,
            filter_method, interlace_method
        ) = IHDR_FIELD_STRUCT.unpack(self.chunk_data)
        self._parse_width_and_height(width, height)
        self._parse_bit_depth(bit_depth)
        self._parse_color_type(color_type)
        self._parse_compression_method(compression_method)
        self._parse_filter_method(filter_method)
        self._parse_interlace_method(interlace_method)
        self._validate_dependencies()

    def repr_contents(self):
        attrs = [
            'width', 'height', 'bit_depth', 'color_type',
            'compression_method', 'filter_method', 'interlace_method'
        ]
        fmt = '{name}={value!r}'
        return ' '.join(
            fmt.format(name=a, value=getattr(self, a)) for a in attrs
        )

    def _validate_length(self):
        if len(self.chunk_data) != IHDR_FIELD_STRUCT.size:
            fmt = (
                "Invalid length for IHDR chunk data, got {actual}, "
                "expected {expected}."
            )
            raise PNGSyntaxError(fmt.format(
                actual=len(self.chunk_data),
                expected=IHDR_FIELD_STRUCT.size
            ))

    def _parse_width_and_height(self, width, height):
        if width > PNG_MAX_HEIGHT or height > PNG_MAX_HEIGHT:
            raise PNGSyntaxError("IHDR width or height is too large")
        if width < PNG_MIN_WIDTH or height < PNG_MIN_WIDTH:
            raise PNGSyntaxError("IHDR width or height is too small")
        self.width = width
        self.height = height

    def _parse_bit_depth(self, bit_depth):
        if bit_depth not in IHDR_ALLOWED_BIT_DEPTHS:
            raise PNGSyntaxError(
                "{depth} is not a supported bit depth".format(bit_depth)
            )
        self.bit_depth = bit_depth

    def _parse_color_type(self, color_type_int):
        try:
            self.color_type = IHDRColorType(color_type_int)
        except ValueError:
            exc = PNGSyntaxError("Invalid IHDR color type {type}".format(
                type=color_type_int
            ))
            raise exc from None

    def _parse_compression_method(self, compression_method_int):
        try:
            self.compression_method = IHDRCompressionMethod(
                compression_method_int
            )
        except ValueError:
            exc = PNGSyntaxError(
                "Invalid IHDR compression method {code}".format(
                    code=compression_method_int
                )
            )
            raise exc from None

    def _parse_filter_method(self, filter_method_int):
        try:
            self.filter_method = IHDRFilterMethod(
                filter_method_int
            )
        except ValueError:
            exc = PNGSyntaxError(
                "Invalid IHDR filter method {0}".format(filter_method_int)
            )
            raise exc from None

    def _parse_interlace_method(self, interlace_method_int):
        try:
            self.interlace_method = IHDRInterlaceMethod(
                interlace_method_int
            )
        except ValueError:
            exc = PNGSyntaxError(
                "Invalid IHDR interlace method {0}".format(interlace_method_int)
            )
            raise exc from None

    def _validate_dependencies(self):
        if not self.color_type.allows_bit_depth(self.bit_depth):
            fmt = (
                "IHDR bit depth {depth} not supported "
                "with color type {typeint}:{type}"
            )
            raise PNGSyntaxError(fmt.format(
                depth=self.bit_depth,
                typeint=self.color_type.value,
                type=self.color_type.name
            ))



@chunk
class PalettePNGChunk(AbstractPNGChunk):
    chunk_type = PNGChunkType(b'PLTE')

    # List of (red, green, blue) byte int tuples
    palette = PNG_CHUNK_DATA_NOT_SET

    def parse(self):
        self._validate_length()
        self._parse_palette()

    def repr_contents(self):
        return ''

    def _validate_length(self):
        length = len(self.chunk_data)
        if length < 3:
            raise PNGSyntaxError("PLTE palette data is too short.")
        if length % 3 != 0:
            raise PNGSyntaxError(
                "PLTE palette length must be a multiple of 3."
            )
        if length // 3 > 256:
            raise PNGSyntaxError("PLTE palette data is too long.")

    def _parse_palette(self):
        it = iter(self.chunk_data)
        palette = list(zip(it, it, it))
        assert 0 < len(palette) <= 256, \
            "Bad palette size {0}".format(len(palette))
        assert len(palette) == len(self.chunk_data) / 3
        self.palette = palette


@chunk
class ImageDataPNGChunk(AbstractPNGChunk):
    chunk_type = PNGChunkType(b'IDAT')

    compressed_data = PNG_CHUNK_DATA_NOT_SET

    def parse(self):
        self.compressed_data = self.chunk_data

    def repr_contents(self):
        return ''


@chunk
class ImageTrailerPNGChunk(AbstractPNGChunk):
    chunk_type = PNGChunkType(b'IEND')

    def parse(self):
        if self.chunk_data:
            raise PNGSyntaxError("IEND chunk must be empty")

    def repr_contents(self):
        return ''


### Ancillary Chunks

# Printable Latin-1, without non-breaking space
TEXTUAL_KEYWORD_ALLOWED_BYTES = frozenset(
    itertools.chain(range(32, 127), range(161, 256)))


@chunk
class PNGImageTextualData(AbstractPNGChunk):
    chunk_type = PNGChunkType(b'tEXt')

    keyword = PNG_CHUNK_DATA_NOT_SET
    text = PNG_CHUNK_DATA_NOT_SET

    def parse(self):
        # TODO: add validation for rules in Textual Information, section 4.2.3
        # of the PNG 1.2 spec.
        components = self.chunk_data.split(b'\x00')
        if len(components) > 2:
            raise PNGSyntaxError(
                "Too many null bytes found in tEXt data."
            )
        if len(components) < 2:
            raise PNGSyntaxError("No null byte found in tEXt data.")
        keyword, text = components
        if not 0 < len(keyword) < 80:
            raise PNGSyntaxError("Invalid length for tEXt keyword.")
        if keyword.startswith(b' ') or keyword.endswith(b' '):
            raise PNGSyntaxError(
                "Forbidden leading or trailing space found in tEXt keyword."
            )
        # No consecutive spaces
        if b'  ' in keyword:
            raise PNGSyntaxError(
                "Forbidden consecutive spaces found in tEXt keyword."
            )
        self.keyword = keyword.decode('latin-1')
        self.text = text.decode('latin-1')

    def repr_contents(self):
        fmt = 'keyword={keyword!r} text={text!r}'
        return fmt.format(keyword=self.keyword, text=self.text)


# TODO: Implement zTXt

# TODO: Implement iTXt


