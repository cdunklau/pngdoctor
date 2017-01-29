import typing

from pngdoctor.lexer import ChunkTokenStream
from pngdoctor.chunk_order_parser import ChunkOrderParser


class PNGParser:
    """
    A parser for PNG images
    """
    _tokens: ChunkTokenStream
    _order: ChunkOrderParser

    def __init__(self, stream: typing.io.BinaryIO):
        """
        :param stream: The binary data stream containing the PNG image
        """
        self._tokens = ChunkTokenStream(stream)
        self._order = ChunkOrderParser()

    def parse(self):
        """
        Run the actual parsing routine.
        """
        raise NotImplementedError('not done yet')
