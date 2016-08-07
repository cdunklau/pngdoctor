"""
Finite state machines.
"""

import collections

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

'''
The PNG chunk code alphabet is the set of strings comprising of exactly four
uppercase or lowercase ASCII letters: (a-zA-Z){4}

png_regular_expression =
    "IHDR"
    (BEFORE_PALETTE|BEFORE_DATA|ALLOWED_ANYWHERE|UNKNOWN) *
    "PLTE" ? 
    (AFTER_PALETTE_BEFORE_DATA|BEFORE_DATA|ALLOWED_ANYWHERE|UNKNOWN) *
    "IDAT" +
    (ALLOWED_ANYWHERE|UNKNOWN) *
    "IEND"

This does not handle the uniqueness constraints in the ancillary chunks.
More research is necessary before I can figure out which formal language
class describes sequences of PNG chunk codes.

'''



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


START_STATE = object()
DELEGATE = object()
INVALID = object()
VALID = object()
COMPLETE = object()


class ChunkGrammarParser(object):
    def __init__(self):
        self.counts = ChunkCountValidator()
        self._critical = CriticalChunkStateMachine()
        self._critical_delegation = {
            b'IHDR': BeforePaletteChunkStateMachine,
            b'PLTE': AfterPaletteBeforeDataStateMachine,
            b'IDAT': AfterDataStateMachine,
        }

    def validate(self, chunk_code):
        # TODO finish this
        self.counts.check(chunk_code)
        critical_result = self._critical.get_result(chunk_code)
        if critical_result is DELEGATE:
            ...
        elif critical_result is VALID:
            ...


class BaseStateMachine(object):
    state = START_STATE
    # Maps current state to set of acceptable next states.
    # State with empty set as next state is an accepting state.
    _transitions = None

    def get_result(self, chunk_code):
        if chunk_code not in self._transitions:
            return DELEGATE
        available = self._transitions[self.state]
        if chunk_code not in available:
            return INVALID

        self.state = chunk_code
        if self._transitions[self.state]:
            return VALID
        else:
            return COMPLETE



class CriticalChunkStateMachine(BaseStateMachine):
    def __init__(self):
        self._transitions = {
            START_STATE: frozenset({b'IHDR'}),
            b'IHDR': frozenset({b'PLTE', b'IDAT'}),
            b'PLTE': frozenset({b'IDAT'}),
            b'IDAT': frozenset({b'IDAT'}),
            b'IEND': frozenset(),
        }


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
            raise PNGSyntaxError(fmt.format(code=chunk_code.encode('ascii')))
        self._nseen[chunk_code] += 1


class BeforePaletteChunkStateMachine(BaseStateMachine):
    def __init__(self):
        self._transitions = {
            START_STATE: frozenset({b'PLTE', b'IDAT'}).union(
                BEFORE_PALETTE,
                BEFORE_DATA,
                ALLOWED_ANYWHERE
            ),
            b'PLTE': frozenset(),
            b'IDAT': frozenset(),
        }


class AfterPaletteBeforeDataStateMachine(BaseStateMachine):
    def __init__(self):
        self._transitions = {
            START_STATE: frozenset({b'IDAT'}).union(
                AFTER_PALETTE_BEFORE_DATA,
                BEFORE_DATA,
                ALLOWED_ANYWHERE
            ),
            b'IDAT': frozenset(),
        }


class AfterDataStateMachine(BaseStateMachine):
    def __init__(self):
        self._transitions = {
            START_STATE: frozenset({b'IEND'}).union(ALLOWED_ANYWHERE),
            b'IEND': frozenset(),
        }
