import sys
import logging

from pngdoctor.decoder import ChunkTokenStream

logger = logging.getLogger(__name__)


def log_chunk_tokens(pngfile):
    tokenizer = ChunkTokenStream(pngfile)
    for token in tokenizer:
        logger.info(repr(token))


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
    with open(sys.argv[1], 'rb') as pngfile:
        log_chunk_tokens(pngfile)
