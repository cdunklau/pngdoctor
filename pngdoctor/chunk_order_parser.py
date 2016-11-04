import collections
import collections.abc
import enum
import logging

from pngdoctor.exceptions import PNGSyntaxError
from pngdoctor import chunktypes


logger = logging.getLogger(__name__)

# ref png-specification-notes.txt

def _code_frozenset(chunk_types):
    """
    Return a `frozenset` instance with the type codes from the
    :class:`models.ChunkType` instances in the input iterable.
    """
    return frozenset(t.code for t in chunk_types)


_CRITICAL_CHUNK_CODES = _code_frozenset({
    chunktypes.IMAGE_HEADER,
    chunktypes.PALETTE,
    chunktypes.IMAGE_DATA,
    chunktypes.IMAGE_TRAILER
})
_BEFORE_PALETTE = _code_frozenset({
    chunktypes.PRIMARY_CHROMATICITIES,
    chunktypes.IMAGE_GAMMA,
    chunktypes.EMBEDDED_ICC_PROFILE,
    chunktypes.SIGNIFICANT_BITS,
    chunktypes.STANDARD_RGB_COLOR_SPACE
})
_AFTER_PALETTE_BEFORE_DATA = _code_frozenset({
    chunktypes.BACKGROUND_COLOR,
    chunktypes.PALETTE_HISTOGRAM,
    chunktypes.TRANSPARENCY
})
_BEFORE_DATA = _code_frozenset({
    chunktypes.PHYSICAL_PIXEL_DIMENSIONS,
    chunktypes.SUGGESTED_PALETTE,
})
_ALLOWED_ANYWHERE = _code_frozenset({
    chunktypes.IMAGE_LAST_MODIFICATION_TIME,
    chunktypes.INTERNATIONAL_TEXTUAL_DATA,
    chunktypes.TEXTUAL_DATA,
    chunktypes.COMPRESSED_TEXTUAL_DATA,
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
assert _KNOWN_CHUNKS == chunktypes.CODE_TO_CHUNK_TYPE.keys()
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
            _ChunkOrderState.before_palette, chunktypes.IMAGE_HEADER.code)

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
            _ChunkOrderState.after_palette_before_data,
            chunktypes.PALETTE.code,
        )
        before_palette_transitions.add_one_transition(
            _ChunkOrderState.during_data, chunktypes.IMAGE_DATA.code)

        after_palette_before_data_transitions = _ChunkOrderStateTransitionMap()
        after_palette_before_data_transitions.set_unknown_chunk_next_state(
            _ChunkOrderState.after_palette_before_data)
        after_palette_before_data_transitions.add_transitions(
            _ChunkOrderState.after_palette_before_data,
            _AFTER_PALETTE_BEFORE_DATA, _BEFORE_DATA, _ALLOWED_ANYWHERE,
        )
        after_palette_before_data_transitions.add_one_transition(
            _ChunkOrderState.during_data, chunktypes.IMAGE_DATA.code)

        during_data_transitions = _ChunkOrderStateTransitionMap()
        during_data_transitions.set_unknown_chunk_next_state(
            _ChunkOrderState.after_data)
        during_data_transitions.add_one_transition(
            _ChunkOrderState.during_data, chunktypes.IMAGE_DATA.code)
        during_data_transitions.add_transitions(
            _ChunkOrderState.after_data, _ALLOWED_ANYWHERE)
        during_data_transitions.add_one_transition(
            _ChunkOrderState.after_trailer, chunktypes.IMAGE_TRAILER.code)

        after_data_transitions = _ChunkOrderStateTransitionMap()
        after_data_transitions.set_unknown_chunk_next_state(
            _ChunkOrderState.after_data)
        after_data_transitions.add_transitions(
            _ChunkOrderState.after_data, _ALLOWED_ANYWHERE)
        after_data_transitions.add_one_transition(
            _ChunkOrderState.after_trailer, chunktypes.IMAGE_TRAILER.code)

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
            chunktypes.IMAGE_DATA,
            chunktypes.SUGGESTED_PALETTE,
            chunktypes.INTERNATIONAL_TEXTUAL_DATA,
            chunktypes.TEXTUAL_DATA,
            chunktypes.COMPRESSED_TEXTUAL_DATA,
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
