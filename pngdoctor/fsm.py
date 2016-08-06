"""
Finite state machines.
"""

import collections

from pngdoctor.exceptions import PNGSyntaxError


START_STATE = object()
DELEGATE = object()
INVALID = object()
VALID = object()
COMPLETE = object()


class ChunkGrammarStateMachine(object):
    def __init__(self):
        self._counts = ChunkCountValidator()
        self._critical = CriticalChunkStateMachine()
        self._critical_delegation = {
            b'IHDR': BeforePaletteChunkStateMachine(),
        }

    def validate(self, chunk_code):
        # TODO finish this
        self._counts.check(chunk_code)
        ...


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

class CriticalChunkStateMachine(object):
    def __init__(self):
        self.state = START_STATE
        # maps current state to 
        self._transitions = {
            START_STATE: frozenset({b'IHDR'}),
            b'IHDR': frozenset({b'PLTE', b'IDAT'}),
            b'PLTE': frozenset({b'IDAT'}),
            b'IDAT': frozenset({b'IDAT'}),
            b'IEND': frozenset(),
        }

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


# From PNG 1.2 specification:
#
# This table summarizes some properties of the standard chunk types.
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


BEFORE_PALETTE = frozenset({b'cHRM', b'gAMA', b'iCCP', b'sBIT', b'sRGB'})
AFTER_PALATTE_BEFORE_DATA = frozenset({b'bKGD', b'hIST', b'tRNS'})
BEFORE_DATA = frozenset({b'pHYs', b'sPLT'})
ALLOWED_ANYWHERE = frozenset({b'tIME', b'iTXt', b'tEXt', b'zTXt'})
_allsets = [
    BEFORE_PALETTE, AFTER_PALATTE_BEFORE_DATA, BEFORE_DATA, ALLOWED_ANYWHERE
]
# Ensure no repeats
assert len(frozenset().union(*_allsets)) == sum(map(len, _allsets))
del _allsets


class BeforePaletteChunkStateMachine(object):
    def __init__(self):
        self.state = START_STATE
        self._transitions = {
            START_STATE: BEFORE_PALETTE | BEFORE_DATA | ALLOWED_ANYWHERE,
            b'PLTE': {},
        }
