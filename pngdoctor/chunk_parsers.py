import abc
import itertools
import logging
import struct
from types import MappingProxyType

from pngdoctor import fieldvalues
from pngdoctor import models
from pngdoctor import chunktypes
from pngdoctor.exceptions import PNGSyntaxError


logger = logging.getLogger(__name__)


class _ParseAntecedent:
    """
    The ongoing results of the parse.
    """
    # TODO: Figure out this API



PNG_MAX_HEIGHT = PNG_MAX_WIDTH = 2**31 - 1
PNG_MIN_WIDTH = PNG_MIN_HEIGHT = 1


PNG_CHUNK_DATA_NOT_SET = object()


class _AbstractLimitedLengthChunkParser(metaclass=abc.ABCMeta):
    """
    Abstract parser class for chunks that have a defined maximum
    data length (at most :data:`decoder.PNG_CHUNK_MAX_DATA_READ`
    bytes).

    Implementers will have their ``__init__`` method called with
    two arguments: the chunk's data token and an instance of
    :class:`_ParseAntecedent` containing the parse results from the
    previous chunks.

    """
    def __init__(self, data_token, parse_antecedent):
        self.data_token = data_token
        self.antecedent = parse_antecedent

    @abc.abstractproperty
    def chunk_type(self):
        """
        The chunk type, an instance of `ChunkType`
        """

    @abc.abstractproperty
    def max_data_size(self):
        """
        Maximum number of bytes allowed for the chunk's data.
        """

    @abc.abstractmethod
    def parse(self):
        """
        Parse the chunk data and return the ChunkModel, or raise
        :exception:`exceptions.PNGSyntaxError` if there was a problem
        parsing the data.
        """

    def _parse_value_to_enum_member(self, enumeration, description, value):
        """
        Return the enumeration member for the value, or raise
        :exception:`exceptions.PNGSyntaxError` if the value is not
        a valid member value.
        """
        if value not in enumeration.__members__.values():
            fmt = "Invalid {description} {value!r} for {code} chunk"
            raise PNGSyntaxError(fmt.format(
                description=description,
                value=value,
                code=self.chunk_type.code.decode('ascii')
            ))
        return enumeration(value)


class _AbstractIterativeChunkParser(metaclass=abc.ABCMeta):
    """
    Abstract parser class for chunks that have an undefined maximum
    data length or larger that :data:`decoder.PNG_CHUNK_MAX_DATA_READ`.

    Implementers will have their ``__init__`` method called with
    one argument: an instance of :class:`_ParseAntecedent` containing
    the parse results from the previous chunks.
    """
    def __init__(self, parse_antecedent):
        self.antecedent = parse_antecedent

    @abc.abstractproperty
    def chunk_type(self):
        """
        The chunk type, an instance of `ChunkType`
        """

    @abc.abstractmethod
    def parse_partial(self, data):
        """
        Process some data bytes from the chunk.

        Raise :exception:`exceptions.PNGSyntaxError` if the parsing
        failed.
        """

    @abc.abstractmethod
    def verify_end(self):
        """
        Verify that the parse up until now represents a complete chunk.

        Return the updated :class:`_ParseAntecedent` instance, or raise
        :exception:`exceptions.PNGSyntaxError` if the end was
        unexpected.
        """


class _ChunkParserRegistry:
    def __init__(self):
        self._store = {}

    def register(self, chunk_parser_class):
        code = chunk_parser_class.chunk_type.code
        if code in self._store:
            raise RuntimeError(
                "Parser for chunk {code} already registered".format(code=code)
            )
        self._store[code] = chunk_parser_class
        return chunk_parser_class


chunk_parsers = _ChunkParserRegistry()


# 4.1. Critical chunks

@chunk_parsers.register
class _ImageHeaderChunkParser(_AbstractLimitedLengthChunkParser):
    # Fields are width, height, bit depth, color type, compression method,
    # filter method, and interlace method
    _FIELD_STRUCT = struct.Struct('>IIBBBBB')

    chunk_type = chunktypes.IMAGE_HEADER
    max_data_size = _FIELD_STRUCT.size  # 13 bytes

    _ALLOWED_BIT_DEPTHS = frozenset([1, 2, 4, 8, 16])
    _COLOR_TYPE_BIT_DEPTHS = MappingProxyType({
        fieldvalues.ColorType.grayscale: frozenset([1, 2, 4, 8, 16]),
        fieldvalues.ColorType.rgb: frozenset([8, 16]),
        fieldvalues.ColorType.indexed: frozenset([1, 2, 4, 8]),
        fieldvalues.ColorType.grayscale_alpha: frozenset([8, 16]),
        fieldvalues.ColorType.rgb_alpha: frozenset([8, 16]),
    })

    def parse(self):
        self._validate_length()
        (
            width, height, bit_depth, color_type, compression_method,
            filter_method, interlace_method
        ) = self._FIELD_STRUCT.unpack(self.data_token)

        self._validate_width_and_height(width, height)
        self._validate_bit_depth(bit_depth)

        color_type = self._parse_value_to_enum_member(
            fieldvalues.ColorType, 'color type', color_type)
        self._validate_bit_depth_allowed_with_color_type(bit_depth, color_type)

        compression_method = self._parse_value_to_enum_member(
            fieldvalues.CompressionMethod,
            'compression method',
            compression_method
        )
        filter_method = self._parse_value_to_enum_member(
            fieldvalues.FilterMethod, 'filter method', filter_method)
        interlace_method = self._parse_value_to_enum_member(
            fieldvalues.InterlaceMethod,
            'interlace method',
            interlace_method
        )
        return models.ImageHeader(
            width,
            height,
            bit_depth,
            color_type,
            compression_method,
            filter_method,
            interlace_method
        )

    def _validate_length(self):
        if len(self.data_token) != self._FIELD_STRUCT.size:
            fmt = (
                "Invalid length for IHDR chunk data, got {actual}, "
                "expected {expected}."
            )
            raise PNGSyntaxError(fmt.format(
                actual=len(self.data_token),
                expected=self._FIELD_STRUCT.size
            ))

    def _validate_width_and_height(self, width, height):
        # pylint: disable=no-self-use
        if width > PNG_MAX_HEIGHT or height > PNG_MAX_HEIGHT:
            raise PNGSyntaxError("IHDR width or height is too large")
        if width < PNG_MIN_WIDTH or height < PNG_MIN_WIDTH:
            raise PNGSyntaxError("IHDR width or height is too small")

    def _validate_bit_depth(self, bit_depth):
        if bit_depth not in self._ALLOWED_BIT_DEPTHS:
            raise PNGSyntaxError(
                "{depth} is not a supported bit depth".format(depth=bit_depth)
            )

    def _validate_bit_depth_allowed_with_color_type(self, bit_depth,
                                                    color_type):
        if bit_depth not in self._COLOR_TYPE_BIT_DEPTHS[color_type]:
            fmt = (
                "IHDR bit depth {depth} not supported "
                "with color type {typeint}:{type}"
            )
            raise PNGSyntaxError(fmt.format(
                depth=bit_depth,
                typeint=color_type.value,
                type=color_type.name
            ))


@chunk_parsers.register
class _PaletteChunkParser(_AbstractLimitedLengthChunkParser):
    chunk_type = chunktypes.PALETTE
    max_data_size = 3 * 256  # 3 bytes per palette entry, max 256 entries

    _PROHIBITED_WITH_COLOR_TYPE = (
        fieldvalues.ColorType.grayscale, fieldvalues.ColorType.grayscale_alpha
    )

    def parse(self):
        self._validate_length()
        self._validate_palette_chunk_allowed()
        return models.Palette(self._parse_palette())

    def _validate_length(self):
        length = len(self.data_token)
        if length < 3:
            raise PNGSyntaxError("PLTE palette data is too short.")
        if length % 3 != 0:
            raise PNGSyntaxError(
                "PLTE palette length must be a multiple of 3."
            )
        if length // 3 > 256:
            raise PNGSyntaxError("PLTE palette data is too long.")
        if (
                self.antecedent.image_header.color_type is
                fieldvalues.ColorType.indexed
            ):
            maximum_size = (2 ** self.antecedent.image_header.bit_depth) * 3
            if length > maximum_size:
                msg = (
                    "Palette length {length} larger than maximum {max} for "
                    "bit depth {depth}"
                )
                raise PNGSyntaxError(msg.format(
                    length=length,
                    max=maximum_size,
                    depth=self.antecedent.image_header.bit_depth
                ))

    def _validate_palette_chunk_allowed(self):
        color_type = self.antecedent.image_header.color_type
        if color_type in self._PROHIBITED_WITH_COLOR_TYPE:
            fmt = 'PLTE chunk not permitted with color type {color_type}'
            raise PNGSyntaxError(fmt.format(color_type=color_type))

    def _parse_palette(self):
        iterator = iter(self.data_token)
        rgb_tuples = list(zip(iterator, iterator, iterator))
        # _validate_length is called before this method
        assert 0 < len(rgb_tuples) <= 256, \
            "Bad palette size {0}".format(len(rgb_tuples))
        assert len(rgb_tuples) == len(self.data_token) / 3  # true division
        return rgb_tuples


#@chunk_parsers.register
class _ImageDataChunkParser(_AbstractIterativeChunkParser):
    chunk_type = chunktypes.IMAGE_DATA
    def __init__(self, antecedent):
        super().__init__(antecedent)
        self._parser = ImageDataStreamParser.from_image_header(
            self.antecedent.image_header)

    def _validate_palette_exists_if_necessary(self):
        if (
                self.antecedent.image_header.color_type ==
                fieldvalues.ColorType.indexed
                and self.antecedent.palette is None
            ):
            raise PNGSyntaxError("Indexed color type but PLTE chunk not found")


#@chunk_parsers.register
class _ImageTrailerChunkParser(_AbstractLimitedLengthChunkParser):
    chunk_type = chunktypes.IMAGE_TRAILER
    max_data_size = 0

    def parse(self):
        if self.data_token:
            raise PNGSyntaxError("IEND chunk must be empty")


# 4.2. Ancillary chunks

# 4.2.1. Transparency information

#@chunk_parsers.register
class _TransparencyChunkParser(_AbstractLimitedLengthChunkParser):
    chunk_type = chunktypes.TRANSPARENCY
    max_data_size = 256  # with color type 3, 1 byte for each palette index
    #TODO
    def parse(self):
        pass


# 4.2.2. Color space information

#@chunk_parsers.register
class _ImageGammaChunkParser(_AbstractLimitedLengthChunkParser):
    chunk_type = chunktypes.IMAGE_GAMMA
    max_data_size = 4
    #TODO
    def parse(self):
        pass


#@chunk_parsers.register
class _PrimaryChromaticitiesChunkParser(_AbstractLimitedLengthChunkParser):
    chunk_type = chunktypes.PRIMARY_CHROMATICITIES
    max_data_size = 32
    #TODO
    def parse(self):
        pass


#@chunk_parsers.register
class _StandardRGBColorSpaceChunkParser(_AbstractLimitedLengthChunkParser):
    chunk_type = chunktypes.STANDARD_RGB_COLOR_SPACE
    max_data_size = 1
    #TODO
    def parse(self):
        pass


#@chunk_parsers.register
class _EmbeddedICCProfileChunkParser(_AbstractIterativeChunkParser):
    chunk_type = chunktypes.EMBEDDED_ICC_PROFILE
    #TODO


# 4.2.3. Textual information

# Printable Latin-1, without non-breaking space
TEXTUAL_KEYWORD_ALLOWED_BYTES = frozenset(
    itertools.chain(range(32, 127), range(161, 256)))


# TODO: Update this and register it once the ABC has been defined
#@chunk_parsers.register
class _TextualDataParser(_AbstractIterativeChunkParser):
    chunk_type = chunktypes.TEXTUAL_DATA

    def parse(self):
        # TODO: add validation for rules in Textual Information, section 4.2.3
        # of the PNG 1.2 spec.
        components = self.data_token.split(b'\x00')
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
        keyword = keyword.decode('latin-1')
        text = text.decode('latin-1')


#@chunk_parsers.register
class _CompressedTextualDataChunkParser(_AbstractIterativeChunkParser):
    chunk_type = chunktypes.COMPRESSED_TEXTUAL_DATA
    #TODO


#@chunk_parsers.register
class _InternationalTextualDataChunkParser(_AbstractIterativeChunkParser):
    chunk_type = chunktypes.INTERNATIONAL_TEXTUAL_DATA
    #TODO


# 4.3.4. Miscellaneous information

#@chunk_parsers.register
class _BackgroundColorChunkParser(_AbstractLimitedLengthChunkParser):
    chunk_type = chunktypes.BACKGROUND_COLOR
    max_data_size = 6  # with color types 2 and 6
    #TODO
    def parse(self):
        pass


#@chunk_parsers.register
class _PhysicalPixelDimensionsChunkParser(_AbstractLimitedLengthChunkParser):
    chunk_type = chunktypes.PHYSICAL_PIXEL_DIMENSIONS
    max_data_size = 9
    #TODO
    def parse(self):
        pass


#@chunk_parsers.register
class _SignificantBitsChunkParser(_AbstractLimitedLengthChunkParser):
    chunk_type = chunktypes.SIGNIFICANT_BITS
    max_data_size = 4
    #TODO
    def parse(self):
        pass


#@chunk_parsers.register
class _SuggestedPaletteChunkParser(_AbstractIterativeChunkParser):
    chunk_type = chunktypes.SUGGESTED_PALETTE
    #TODO


#@chunk_parsers.register
class _PaletteHistogramChunkParser(_AbstractLimitedLengthChunkParser):
    chunk_type = chunktypes.PALETTE_HISTOGRAM
    max_data_size = 512
    #TODO
    def parse(self):
        pass


#@chunk_parsers.register
class _ImageLastModificationTimeChunkParser(_AbstractLimitedLengthChunkParser):
    chunk_type = chunktypes.IMAGE_LAST_MODIFICATION_TIME
    max_data_size = 7
    #TODO
    def parse(self):
        pass
