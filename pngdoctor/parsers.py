import collections
import collections.abc
import enum
import logging

from pngdoctor.exceptions import PNGSyntaxError
from pngdoctor import models


logger = logging.getLogger(__name__)

# From PNG 1.2 specification:
#
# This table summarizes some properties of the standard chunk types.
#
# Critical chunks (must appear in this order, except PLTE
#                  is optional):
#
#         Name  Multiple  Ordering constraints
#                 OK?
#
#         IHDR    No      Must be first
#         PLTE    No      Before IDAT
#         IDAT    Yes     Multiple IDATs must be consecutive
#         IEND    No      Must be last
#
# Ancillary chunks (need not appear in this order):
#
#         Name  Multiple  Ordering constraints
#                 OK?
#
#         cHRM    No      Before PLTE and IDAT
#         gAMA    No      Before PLTE and IDAT
#         iCCP    No      Before PLTE and IDAT
#         sBIT    No      Before PLTE and IDAT
#         sRGB    No      Before PLTE and IDAT
#         bKGD    No      After PLTE; before IDAT
#         hIST    No      After PLTE; before IDAT
#         tRNS    No      After PLTE; before IDAT
#         pHYs    No      Before IDAT
#         sPLT    Yes     Before IDAT
#         tIME    No      None
#         iTXt    Yes     None
#         tEXt    Yes     None
#         zTXt    Yes     None

def code_frozenset(chunk_types):
    return frozenset(t.code for t in chunk_types)


CRITICAL = code_frozenset({
    models.IMAGE_HEADER,
    models.PALETTE,
    models.IMAGE_DATA,
    models.IMAGE_TRAILER
})
BEFORE_PALETTE = code_frozenset({
    models.PRIMARY_CHROMATICITIES,
    models.IMAGE_GAMMA,
    models.EMBEDDED_ICC_PROFILE,
    models.SIGNIFICANT_BITS,
    models.STANDARD_RGB_COLOR_SPACE
})
AFTER_PALETTE_BEFORE_DATA = code_frozenset({
    models.BACKGROUND_COLOR,
    models.PALETTE_HISTOGRAM,
    models.TRANSPARENCY
})
BEFORE_DATA = code_frozenset({
    models.PHYSICAL_PIXEL_DIMENSIONS,
    models.SUGGESTED_PALETTE,
})
ALLOWED_ANYWHERE = code_frozenset({
    models.IMAGE_LAST_MODIFICATION_TIME,
    models.INTERNATIONAL_TEXTUAL_DATA,
    models.TEXTUAL_DATA,
    models.COMPRESSED_TEXTUAL_DATA,
})
_allsets = [
    CRITICAL,
    BEFORE_PALETTE,
    AFTER_PALETTE_BEFORE_DATA,
    BEFORE_DATA,
    ALLOWED_ANYWHERE
]
KNOWN_CHUNKS = frozenset().union(*_allsets)
# Ensure no repeats
assert len(KNOWN_CHUNKS) == sum(map(len, _allsets))
# Ensure everything is covered
assert KNOWN_CHUNKS == models.CODE_TYPES.keys()
del _allsets


@enum.unique
class ChunkOrderState(enum.Enum):
    before_header = 0
    before_palette = 1
    after_palette_before_data = 2
    during_data = 3
    after_data = 4
    after_trailer = 5


class ChunkOrderParser(object):
    def __init__(self):
        self.state = ChunkOrderState.before_header
        self.counts = ChunkCountValidator()

        before_header_transitions = ChunkOrderStateTransitionMap()
        before_header_transitions.add_one_transition(
            ChunkOrderState.before_palette, models.IMAGE_HEADER.code)

        before_palette_transitions = ChunkOrderStateTransitionMap()
        before_palette_transitions.set_unknown_chunk_next_state(
            ChunkOrderState.before_palette)
        before_palette_transitions.add_transitions(
            ChunkOrderState.before_palette,
            BEFORE_PALETTE, BEFORE_DATA, ALLOWED_ANYWHERE,
        )
        before_palette_transitions.add_transitions(
            ChunkOrderState.after_palette_before_data,
            AFTER_PALETTE_BEFORE_DATA
        )
        before_palette_transitions.add_one_transition(
            ChunkOrderState.after_palette_before_data, models.PALETTE.code)
        before_palette_transitions.add_one_transition(
            ChunkOrderState.during_data, models.IMAGE_DATA.code)

        after_palette_before_data_transitions = ChunkOrderStateTransitionMap()
        after_palette_before_data_transitions.set_unknown_chunk_next_state(
            ChunkOrderState.after_palette_before_data)
        after_palette_before_data_transitions.add_transitions(
            ChunkOrderState.after_palette_before_data,
            AFTER_PALETTE_BEFORE_DATA, BEFORE_DATA, ALLOWED_ANYWHERE,
        )
        after_palette_before_data_transitions.add_one_transition(
            ChunkOrderState.during_data, models.IMAGE_DATA.code)

        during_data_transitions = ChunkOrderStateTransitionMap()
        during_data_transitions.set_unknown_chunk_next_state(
            ChunkOrderState.after_data)
        during_data_transitions.add_one_transition(
            ChunkOrderState.during_data, models.IMAGE_DATA.code)
        during_data_transitions.add_transitions(
            ChunkOrderState.after_data, ALLOWED_ANYWHERE)
        during_data_transitions.add_one_transition(
            ChunkOrderState.after_trailer, models.IMAGE_TRAILER.code)

        after_data_transitions = ChunkOrderStateTransitionMap()
        after_data_transitions.set_unknown_chunk_next_state(
            ChunkOrderState.after_data)
        after_data_transitions.add_transitions(
            ChunkOrderState.after_data, ALLOWED_ANYWHERE)
        after_data_transitions.add_one_transition(
            ChunkOrderState.after_trailer, models.IMAGE_TRAILER.code)

        self._transitions = {
            ChunkOrderState.before_header: before_header_transitions,
            ChunkOrderState.before_palette: before_palette_transitions,
            ChunkOrderState.after_palette_before_data:
                after_palette_before_data_transitions,
            ChunkOrderState.during_data: during_data_transitions,
            ChunkOrderState.after_data: after_data_transitions,
            # End state
            ChunkOrderState.after_trailer: {},
        }


        assert set(ChunkOrderState) == self._transitions.keys()

    def validate(self, chunk_code):
        msg = 'In state {state}, validating code {code}'.format(
            state=self.state, code=chunk_code
        )
        logging.debug(msg)
        self.counts.check(chunk_code)
        available_transitions = self._transitions[self.state]
        if chunk_code not in available_transitions:
            raise PNGSyntaxError(
                'Chunk {code} is not allowed here'.format(code=chunk_code)
            )
        next_state = available_transitions[chunk_code]
        if next_state is self.state:
            msg = 'Staying in state {state}'.format(state=self.state)
            logging.debug(msg)
        else:
            msg = 'Changing state to {next}'.format(next=next_state)
            logging.debug(msg)
        self.state = next_state

    def validate_end(self):
        """
        Raise an exception if the last chunk seen was not IEND.
        """
        if self.state is not ChunkOrderState.after_trailer:
            raise PNGSyntaxError('Missing IEND')


class ChunkCountValidator(object):
    def __init__(self):
        self._nseen = collections.Counter()
        self._multiple_allowed = code_frozenset({
            models.IMAGE_DATA,
            models.SUGGESTED_PALETTE,
            models.INTERNATIONAL_TEXTUAL_DATA,
            models.TEXTUAL_DATA,
            models.COMPRESSED_TEXTUAL_DATA,
        })

    def check(self, chunk_code):
        if (self._nseen[chunk_code] > 1 and
                chunk_code not in self._multiple_allowed):
            fmt = 'More than one {code} chunk seen, but at most one allowed'
            raise PNGSyntaxError(fmt.format(code=chunk_code.decode('ascii')))
        self._nseen[chunk_code] += 1


class ChunkOrderStateTransitionMap(collections.abc.Mapping):
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
        if not isinstance(next_state, ChunkOrderState):
            fmt = 'Next state must be ChunkOrderState, not {type}'
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
                    or key in KNOWN_CHUNKS):
                raise
            return self._unknown_chunk_next_state

    def __iter__(self):
        return iter(self._map)

    def __len__(self):
        return len(self._map)
