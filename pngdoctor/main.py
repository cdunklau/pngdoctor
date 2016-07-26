import sys
import logging

from pngdoctor.decoder import PNGLexer
from pngdoctor.models import UnknownPNGChunk

logger = logging.getLogger(__name__)


def log_details(chunk):
    if isinstance(chunk, UnknownPNGChunk):
        log = logger.warning
        fmt = "Got unknown chunk with code {code!r}, {length} bytes: {obj!r}"
    else:
        log = logger.info
        fmt = "Got {code} chunk, {length} bytes: {obj!r}"

    log(fmt.format(
        code=chunk.chunk_type.code,
        length=chunk.data_length,
        obj=chunk
    ))


def log_chunks(pngfile):
    lex = PNGLexer(pngfile)
    for chunk in lex.iter_chunks():
        log_details(chunk)


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    with open(sys.argv[1], 'rb') as pngfile:
        log_chunks(pngfile)
