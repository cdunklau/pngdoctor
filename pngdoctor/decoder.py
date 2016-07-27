import struct
import zlib

from pngdoctor import exceptions
from pngdoctor import models


PNG_SIGNATURE = bytes([
    # High bit set to detect non-8-bit-clean transmission
    0x89,
    # ASCII letters PNG
    0x50, 0x4E, 0x47,
    # DOS line ending (CRLF)
    0x0D, 0x0A,
    # end-of-file charater
    0x1A,
    # Unix line ending (LF)
    0x0A
])
PNG_MAX_FILE_SIZE = 20 * 2**20  # 20 MiB is large enough for most reasonable PNGs
PNG_MAX_CHUNK_LENGTH = 2**31 - 1
PNG_CHUNK_MAX_DATA_READ = 4 * 2**10  # 4 KiB max chunk data processed


class PNGChunkDataStream(object):
    """
    Produces chunks and partial chunks for processing in the higher
    levels of the decoder.

    Responsible for parsing and validating low-level portions of a
    PNG stream, including:

    -   Signature (PNG magic number)
    -   Valid chunk length declaration
    -   Valid chunk code
    -   CRC32 checksum
    -   Proper ordering of chunks: IHDR first, contiguous IDAT,
        terminal IEND, etc

    :ivar chunk_state: The state of the current chunk's processing
    :type chunk_state: :class:`PNGChunkState`
    """

    total_bytes_read = None
    "Total number of bytes consumed from the underlying file object"

    chunk_data_bytes_read = None
    "Number of bytes consumed during processing of the current chunk"



class PNGChunkState(object):
    """
    Represents the state of processing of a single chunk.

    No attribute may be modified externally.

    :ivar data_length: The total length in bytes of the chunk's data
    :type data_length: int
    :ivar code: The PNG chunk code
    :type code: bytes
    :ivar data_remaining:
        The number of chunk data bytes not yet processed
    :type data_remaining: int
    :ivar crc32: The running crc32 checksum
    :type crc32: int
    :ivar next_read:
        The number of bytes for the PNGChunkDataStream to provide to
        the next call of instance's `update` method.
    :type next_read: int

    """
    def __init__(self, length, code):
        self.data_length = self.data_remaining = length
        self.code = code
        self.crc32 = 0
        self._update_next_read()

    def update(self, data):
        """
        Update the state with the provided data, which must be
        :attr:`next_read` bytes long.
        """
        assert self.data_remaining >= len(data) == self.next_read
        self.data_remaining -= self.next_read
        self._update_next_read()
        self.crc32 = zlib.crc32(data, self.crc32)

    def _update_next_read(self):
        self.next_read = min(PNG_CHUNK_MAX_DATA_READ, self.data_remaining)


class PNGLexer(object):
    def __init__(self, stream):
        self._stream = stream
        self._nbytes_read = 0

    def iter_chunks(self):
        ihdr = None
        for code, data in self.iter_chunk_type_and_data():
            chunkcls = models.chunk_registry.get(code, models.UnknownPNGChunk)
            if ihdr is None:
                assert chunkcls is models.ImageHeaderPNGChunk
                chunk = ihdr = chunkcls(data, None)
            else:
                chunk = chunkcls(data, ihdr)
            if chunkcls is models.UnknownPNGChunk:
                chunk.chunk_type = models.PNGChunkType(code)
            chunk.parse()
            yield chunk

    def iter_chunk_type_and_data(self):
        self._validate_signature()

        chunk = self._get_next_chunk()
        if chunk[0] != b'IHDR':
            raise exceptions.PNGSyntaxError("First chunk expected to be IHDR")
        yield chunk

        while True:
            chunk = self._get_next_chunk()
            yield chunk
            if chunk[0] == b'IEND':
                break

        # Ensure we are at EOF
        try:
            self._read(1)
        except exceptions.UnexpectedEOF:
            return
        else:
            raise exceptions.PNGSyntaxError(
                "Data exists beyond IEND chunk end"
            )

    def _get_next_chunk(self):
        """
        Read the next chunk in the file and ensure the CRC matches.

        Return a tuple of (chunk_type, chunk_data), both are bytes.
        """
        chunk_start_position = self._nbytes_read + 1
        length, = struct.unpack('>I', self._read(4))
        if length > PNG_MAX_CHUNK_LENGTH:
            fmt = (
                "Chunk claims to be {actual} bytes long, must be "
                "no longer than {max}."
            )
            raise exceptions.PNGSyntaxError(fmt.format(
                actual=length,
                max=PNG_MAX_CHUNK_LENGTH
            ))
        chunk_type = self._read(4)
        chunk_data = self._read(length)
        expected_crc, = struct.unpack('>I', self._read(4))
        computed_crc = zlib.crc32(chunk_type)
        computed_crc = zlib.crc32(chunk_data, computed_crc)
        if expected_crc != computed_crc:
            fmt = (
                "CRC check failed for chunk starting at position {pos}, "
                "expected {expected:#08x}, computed {computed:#08x}."
            )
            raise exceptions.BadCRC(fmt.format(
                pos=chunk_start_position,
                expected=expected_crc,
                computed=computed_crc
            ))
        return chunk_type, chunk_data

    def _read(self, length):
        """
        Read ``length`` bytes from the stream, update _nbytes_read, and
        return the bytes.

        If the read results in fewer bytes than requested, raise
        `UnexpectedEOF`.
        """
        if length + self._nbytes_read > PNG_MAX_FILE_SIZE:
            raise exceptions.PNGTooLarge(
                "Attempted to read past file size limit: {size} bytes".format(
                    size=PNG_MAX_FILE_SIZE,
                )
            )
        read = self._stream.read(length)
        actual = len(read)
        self._nbytes_read += actual
        assert length >= actual, "Read more bytes than requested"
        if length > actual:
            fmt = "Expected to read {length}, got {actual}, total read {total}"
            raise exceptions.UnexpectedEOF(
                fmt.format(
                    length=length,
                    actual=actual,
                    total=self._nbytes_read
                )
            )
        return read

    def _validate_signature(self):
        header = self._read(len(PNG_SIGNATURE))
        if header != PNG_SIGNATURE:
            raise exceptions.SignatureMismatch(
                "Expected {expected!r}, got {actual!r}".format(
                    expected=PNG_SIGNATURE,
                    actual=header
                )
            )
