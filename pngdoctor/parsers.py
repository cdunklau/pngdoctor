import collections
import collections.abc
import enum

from pngdoctor.exceptions import PNGSyntaxError


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

@enum.unique
class ChunkOrderState(enum.Enum):
    before_header = 0
    before_palette = 1
    after_palette_before_data = 2
    during_data = 3
    after_data = 4
    after_trailer = 5


# These might still be useful, so leaving them for now
CRITICAL = frozenset({b'IHDR', b'PLTE', b'IDAT', b'IEND'})
BEFORE_PALETTE = frozenset({b'cHRM', b'gAMA', b'iCCP', b'sBIT', b'sRGB'})
AFTER_PALETTE_BEFORE_DATA = frozenset({b'bKGD', b'hIST', b'tRNS'})
BEFORE_DATA = frozenset({b'pHYs', b'sPLT'})
ALLOWED_ANYWHERE = frozenset({b'tIME', b'iTXt', b'tEXt', b'zTXt'})
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
del _allsets


class ChunkOrderParser(object):
    def __init__(self):
        self.state = ChunkOrderState.before_header
        self.counts = ChunkCountValidator()

        s = ChunkOrderState

        before_header_transitions = ChunkOrderStateTransitionMap()
        before_header_transitions.add_one_transition(
            s.before_palette, b'IHDR')

        before_palette_transitions = ChunkOrderStateTransitionMap()
        before_palette_transitions.set_unknown_chunk_next_state(
            s.before_palette)
        before_palette_transitions.add_transitions(
            s.before_palette,
            BEFORE_PALETTE, BEFORE_DATA, ALLOWED_ANYWHERE,
        )
        before_palette_transitions.add_transitions(
            s.after_palette_before_data,
            AFTER_PALETTE_BEFORE_DATA
        )
        before_palette_transitions.add_one_transition(
            s.after_palette_before_data, b'PLTE')
        before_palette_transitions.add_one_transition(s.during_data, b'IDAT')

        # TODO: Finish converting these
        after_palette_before_data_transitions = {}
        after_palette_before_data_transitions.update({
            code: s.after_palette_before_data
            for code in AFTER_PALETTE_BEFORE_DATA.union(
                BEFORE_DATA, ALLOWED_ANYWHERE
            )
        })
        after_palette_before_data_transitions[b'IDAT'] = s.during_data

        during_data_transitions = {b'IDAT': s.during_data}
        during_data_transitions.update({
            code: s.after_data for code in ALLOWED_ANYWHERE
        })
        during_data_transitions[b'IEND'] = s.after_trailer

        after_data_transitions = {}
        after_data_transitions.update({
            code: s.after_data for code in ALLOWED_ANYWHERE
        })

        self._transitions = {
            s.before_header: before_header_transitions,
            s.before_palette: before_palette_transitions,
            s.after_palette_before_data: after_palette_before_data_transitions,
            s.during_data: during_data_transitions,
            s.after_data: after_data_transitions,
            # End state
            s.after_trailer: {},
        }


        assert set(ChunkOrderState) == self._transitions.keys()

    def validate(self, chunk_code):
        self.counts.check(chunk_code)
        available_transitions = self._transitions[self.state]
        if chunk_code not in available_transitions:
            raise PNGSyntaxError(
                'Chunk {code} is not allowed here'.format(code=chunk_code)
            )
        self.state = available_transitions[chunk_code]

    def validate_end(self):
        """
        Raise an exception if the last chunk seen was not IEND.
        """
        if self.state is not ChunkOrderState.after_trailer:
            raise PNGSyntaxError('Missing IEND')


class ChunkCountValidator(object):
    def __init__(self):
        self._nseen = collections.Counter()
        self._multiple_allowed = frozenset({
            b'IDAT', b'sPLT', b'iTXt', b'tEXt', b'zTXt',
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
