import abc
import collections
import collections.abc
import enum
import itertools
import logging
import struct
from types import MappingProxyType

from pngdoctor.exceptions import PNGSyntaxError
from pngdoctor import models


logger = logging.getLogger(__name__)

# ref png-specification-notes.txt

def _code_frozenset(chunk_types):
    """
    Return a `frozenset` instance with the type codes from the
    :class:`models.ChunkType` instances in the input iterable.
    """
    return frozenset(t.code for t in chunk_types)


_CRITICAL_CHUNK_CODES = _code_frozenset({
    models.IMAGE_HEADER,
    models.PALETTE,
    models.IMAGE_DATA,
    models.IMAGE_TRAILER
})
_BEFORE_PALETTE = _code_frozenset({
    models.PRIMARY_CHROMATICITIES,
    models.IMAGE_GAMMA,
    models.EMBEDDED_ICC_PROFILE,
    models.SIGNIFICANT_BITS,
    models.STANDARD_RGB_COLOR_SPACE
})
_AFTER_PALETTE_BEFORE_DATA = _code_frozenset({
    models.BACKGROUND_COLOR,
    models.PALETTE_HISTOGRAM,
    models.TRANSPARENCY
})
_BEFORE_DATA = _code_frozenset({
    models.PHYSICAL_PIXEL_DIMENSIONS,
    models.SUGGESTED_PALETTE,
})
_ALLOWED_ANYWHERE = _code_frozenset({
    models.IMAGE_LAST_MODIFICATION_TIME,
    models.INTERNATIONAL_TEXTUAL_DATA,
    models.TEXTUAL_DATA,
    models.COMPRESSED_TEXTUAL_DATA,
})
_allsets = [
    _CRITICAL_CHUNK_CODES,
    _BEFORE_PALETTE,
    _AFTER_PALETTE_BEFORE_DATA,
    _BEFORE_DATA,
    _ALLOWED_ANYWHERE
]
_KNOWN_CHUNKS = frozenset().union(*_allsets)
# Ensure no repeats
assert len(_KNOWN_CHUNKS) == sum(map(len, _allsets))
# Ensure everything is covered
assert _KNOWN_CHUNKS == models.CODE_TYPES.keys()
del _allsets


@enum.unique
class _ChunkOrderState(enum.Enum):
    before_header = 0
    before_palette = 1
    after_palette_before_data = 2
    during_data = 3
    after_data = 4
    after_trailer = 5


class ChunkOrderParser(object):
    """
    Ensure that the sequence of chunk type codes for a PNG stream is
    valid according to the PNG 1.2 specification.

    Call :meth:`validate` with each chunk type code (4 bytes) as they
    appear in the stream. When the stream is complete, call
    :meth:`validate_end` to ensure the end state was reached.

    """
    def __init__(self):
        self._state = _ChunkOrderState.before_header
        self._counts = _ChunkCountValidator()

        before_header_transitions = _ChunkOrderStateTransitionMap()
        before_header_transitions.add_one_transition(
            _ChunkOrderState.before_palette, models.IMAGE_HEADER.code)

        before_palette_transitions = _ChunkOrderStateTransitionMap()
        before_palette_transitions.set_unknown_chunk_next_state(
            _ChunkOrderState.before_palette)
        before_palette_transitions.add_transitions(
            _ChunkOrderState.before_palette,
            _BEFORE_PALETTE, _BEFORE_DATA, _ALLOWED_ANYWHERE,
        )
        before_palette_transitions.add_transitions(
            _ChunkOrderState.after_palette_before_data,
            _AFTER_PALETTE_BEFORE_DATA
        )
        before_palette_transitions.add_one_transition(
            _ChunkOrderState.after_palette_before_data, models.PALETTE.code)
        before_palette_transitions.add_one_transition(
            _ChunkOrderState.during_data, models.IMAGE_DATA.code)

        after_palette_before_data_transitions = _ChunkOrderStateTransitionMap()
        after_palette_before_data_transitions.set_unknown_chunk_next_state(
            _ChunkOrderState.after_palette_before_data)
        after_palette_before_data_transitions.add_transitions(
            _ChunkOrderState.after_palette_before_data,
            _AFTER_PALETTE_BEFORE_DATA, _BEFORE_DATA, _ALLOWED_ANYWHERE,
        )
        after_palette_before_data_transitions.add_one_transition(
            _ChunkOrderState.during_data, models.IMAGE_DATA.code)

        during_data_transitions = _ChunkOrderStateTransitionMap()
        during_data_transitions.set_unknown_chunk_next_state(
            _ChunkOrderState.after_data)
        during_data_transitions.add_one_transition(
            _ChunkOrderState.during_data, models.IMAGE_DATA.code)
        during_data_transitions.add_transitions(
            _ChunkOrderState.after_data, _ALLOWED_ANYWHERE)
        during_data_transitions.add_one_transition(
            _ChunkOrderState.after_trailer, models.IMAGE_TRAILER.code)

        after_data_transitions = _ChunkOrderStateTransitionMap()
        after_data_transitions.set_unknown_chunk_next_state(
            _ChunkOrderState.after_data)
        after_data_transitions.add_transitions(
            _ChunkOrderState.after_data, _ALLOWED_ANYWHERE)
        after_data_transitions.add_one_transition(
            _ChunkOrderState.after_trailer, models.IMAGE_TRAILER.code)

        self._transitions = {
            _ChunkOrderState.before_header: before_header_transitions,
            _ChunkOrderState.before_palette: before_palette_transitions,
            _ChunkOrderState.after_palette_before_data:
                after_palette_before_data_transitions,
            _ChunkOrderState.during_data: during_data_transitions,
            _ChunkOrderState.after_data: after_data_transitions,
            # End state
            _ChunkOrderState.after_trailer: {},
        }

        assert set(_ChunkOrderState) == self._transitions.keys()

    def validate(self, chunk_code):
        """
        Ensure that the chunk type code is valid for the current
        parser state, and change the state as necessary.
        """
        msg = 'In state {state}, validating code {code}'.format(
            state=self._state, code=chunk_code
        )
        logging.debug(msg)
        self._counts.check(chunk_code)
        available_transitions = self._transitions[self._state]
        if chunk_code not in available_transitions:
            raise PNGSyntaxError(
                'Chunk {code} is not allowed here'.format(code=chunk_code)
            )
        next_state = available_transitions[chunk_code]
        if next_state is self._state:
            msg = 'Staying in state {state}'.format(state=self._state)
            logging.debug(msg)
        else:
            msg = 'Changing state to {next}'.format(next=next_state)
            logging.debug(msg)
        self._state = next_state

    def validate_end(self):
        """
        Raise an exception if the last chunk seen was not IEND.
        """
        if self._state is not _ChunkOrderState.after_trailer:
            raise PNGSyntaxError('Missing IEND')


class _ChunkCountValidator(object):
    def __init__(self):
        self._nseen = collections.Counter()
        self._multiple_allowed = _code_frozenset({
            models.IMAGE_DATA,
            models.SUGGESTED_PALETTE,
            models.INTERNATIONAL_TEXTUAL_DATA,
            models.TEXTUAL_DATA,
            models.COMPRESSED_TEXTUAL_DATA,
        })

    def check(self, chunk_code):
        seen_and_multiple_disallowed = (
            self._nseen[chunk_code] >= 1 and
            chunk_code not in self._multiple_allowed and
            chunk_code in _KNOWN_CHUNKS
        )
        if seen_and_multiple_disallowed:
            fmt = 'More than one {code} chunk seen, but at most one allowed'
            raise PNGSyntaxError(fmt.format(code=chunk_code.decode('ascii')))
        self._nseen[chunk_code] += 1


class _ChunkOrderStateTransitionMap(collections.abc.Mapping):
    """
    Mapping for state transitions in :class:`ChunkOrderParser`.

    Although this structure is mutable with methods, it doesn't
    implement MutableMapping because it shouldn't be mutated after
    the initial configuration.
    """
    def __init__(self):
        self._map = {}
        self._unknown_chunk_next_state = None

    def add_one_transition(self, next_state, chunk_code):
        """
        Add a single transition.
        """
        if chunk_code in self._map:
            raise ValueError('Chunk code {code} already in mapping'.format(
                code=chunk_code
            ))
        if not isinstance(next_state, _ChunkOrderState):
            fmt = 'Next state must be _ChunkOrderState, not {type}'
            raise TypeError(fmt.format(type=type(next_state)))
        if not isinstance(chunk_code, bytes):
            raise TypeError('Chunk code must be bytes, not {type}'.format(
                type=type(chunk_code)
            ))
        self._map[chunk_code] = next_state

    def add_transitions(self, next_state, *chunk_code_sets):
        for chunk_codes in chunk_code_sets:
            for chunk_code in chunk_codes:
                self.add_one_transition(next_state, chunk_code)

    def set_unknown_chunk_next_state(self, next_state):
        self._unknown_chunk_next_state = next_state

    def __getitem__(self, key):
        try:
            return self._map[key]
        except KeyError:
            if (self._unknown_chunk_next_state is None
                    # Ensure we don't allow unwanted state transitions
                    or key in _KNOWN_CHUNKS):
                raise
            return self._unknown_chunk_next_state

    def __iter__(self):
        return iter(self._map)

    def __len__(self):
        return len(self._map)



class _ParseAnecedent:
    """
    The ongoing results of the parse.
    """



PNG_MAX_HEIGHT = PNG_MAX_WIDTH = 2**31 - 1
PNG_MIN_WIDTH = PNG_MIN_HEIGHT = 1


PNG_CHUNK_DATA_NOT_SET = object()


class _AbstractLimitedLengthChunkParser(metaclass=abc.ABCMeta):
    """
    Abstract parser class for chunks that have a defined maximum
    data length (at most :data:`decoder.PNG_CHUNK_MAX_DATA_READ`
    bytes).
    """
    def __init__(self, chunk_data, parse_antecedent):
        self.chunk_data = chunk_data
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
        Parse the chunk data and return the ChunkModel.

        Raise PNGSyntaxError if there was a problem parsing the data.
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
    # TODO: Define this ABC
    def __init__(self, chunk_data, parse_antecedent):
        # TODO: fix this to not have the whole chunk data passed in. Probably
        # need to have partial data passed into the parsing method.
        self.chunk_data = chunk_data
        self.antecedent = parse_antecedent

    @abc.abstractproperty
    def chunk_type(self):
        """
        The chunk type, an instance of `ChunkType`
        """



# Map of chunk type code -> chunk class
_chunk_parser_registry = {}


def _chunk_parser(cls):
    code = cls.chunk_type.code
    if code in _chunk_parser_registry:
        raise RuntimeError("Parser for chunk {code} already registered".format(
            code=code
        ))
    _chunk_parser_registry[code] = cls
    return cls


# Critical Chunks
@_chunk_parser
class _ImageHeaderChunkParser(_AbstractLimitedLengthChunkParser):
    # Fields are width, height, bit depth, color type, compression method,
    # filter method, and interlace method
    _FIELD_STRUCT = struct.Struct('>IIBBBBB')

    chunk_type = models.IMAGE_HEADER
    max_data_size = _FIELD_STRUCT.size  # 13 bytes

    _ALLOWED_BIT_DEPTHS = frozenset([1, 2, 4, 8, 16])
    _COLOR_TYPE_BIT_DEPTHS = MappingProxyType({
        models.ImageHeaderColorType.grayscale: frozenset([1, 2, 4, 8, 16]),
        models.ImageHeaderColorType.rgb: frozenset([8, 16]),
        models.ImageHeaderColorType.palette: frozenset([1, 2, 4, 8]),
        models.ImageHeaderColorType.grayscale_alpha: frozenset([8, 16]),
        models.ImageHeaderColorType.rgb_alpha: frozenset([8, 16]),
    })

    def parse(self):
        self._validate_length()
        (
            width, height, bit_depth, color_type, compression_method,
            filter_method, interlace_method
        ) = self._FIELD_STRUCT.unpack(self.chunk_data)

        self._validate_width_and_height(width, height)
        self._validate_bit_depth(bit_depth)

        color_type = self._parse_value_to_enum_member(
            models.ImageHeaderColorType, 'color type', color_type)
        self._validate_bit_depth_allowed_with_color_type(bit_depth, color_type)

        compression_method = self._parse_value_to_enum_member(
            models.CompressionMethod, 'compression method', compression_method)
        filter_method = self._parse_value_to_enum_member(
            models.ImageHeaderFilterMethod, 'filter method', filter_method)
        interlace_method = self._parse_value_to_enum_member(
            models.ImageHeaderInterlaceMethod,
            'interlace method',
            interlace_method
        )
        # TODO: return a thing

    def _validate_length(self):
        if len(self.chunk_data) != self._FIELD_STRUCT.size:
            fmt = (
                "Invalid length for IHDR chunk data, got {actual}, "
                "expected {expected}."
            )
            raise PNGSyntaxError(fmt.format(
                actual=len(self.chunk_data),
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


@_chunk_parser
class _PaletteChunkParser(_AbstractLimitedLengthChunkParser):
    chunk_type = models.PALETTE
    max_data_size = 3 * 256  # 3 bytes per palette entry, max 256 entries

    def parse(self):
        self._validate_length()
        # pylint: disable=unused-variable
        rgb_tuples = self._parse_palette()
        # TODO: return a thing

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
        iterator = iter(self.chunk_data)
        rgb_tuples = list(zip(iterator, iterator, iterator))
        # _validate_length is called before this method
        assert 0 < len(rgb_tuples) <= 256, \
            "Bad palette size {0}".format(len(rgb_tuples))
        assert len(rgb_tuples) == len(self.chunk_data) / 3  # true division
        return rgb_tuples



@_chunk_parser
class _ImageTrailerChunkParser(_AbstractLimitedLengthChunkParser):
    chunk_type = models.IMAGE_TRAILER
    max_data_size = 0

    def parse(self):
        if self.chunk_data:
            raise PNGSyntaxError("IEND chunk must be empty")


# Ancillary Chunks

# Printable Latin-1, without non-breaking space
TEXTUAL_KEYWORD_ALLOWED_BYTES = frozenset(
    itertools.chain(range(32, 127), range(161, 256)))


# TODO: Update this and register it once the ABC has been defined
#@_chunk_parser
class _TextualDataParser(_AbstractIterativeChunkParser):
    chunk_type = models.TEXTUAL_DATA

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
        keyword = keyword.decode('latin-1')
        text = text.decode('latin-1')

# TODO: Implement zTXt

# TODO: Implement iTXt
