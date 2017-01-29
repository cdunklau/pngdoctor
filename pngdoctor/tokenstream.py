import struct
import zlib

from pngdoctor import exceptions as exc
from pngdoctor import models
from pngdoctor.chunk_order_parser import ChunkOrderParser


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
PNG_MAX_FILE_SIZE = 20 * 2**20  # 20 MiB is large enough for reasonable PNGs
PNG_MAX_CHUNK_LENGTH = 2**31 - 1  # Max length of chunk data


# TODO: Pull the order validation out. The lowest level of the decoder should
# only be concerned with framing.
class ChunkTokenStream(object):
    """
    Produces chunk tokens for processing in the higher levels of the
    decoder.

    Responsible for parsing and validating low-level portions of a
    PNG stream, including:

    -   Signature (PNG magic number)
    -   Valid chunk length declaration
    -   Valid chunk code
    -   CRC32 checksum
    -   Ordering of chunks

    :ivar total_bytes_read:
        Total number of bytes consumed from the underlying file object
    :type total_bytes_read: int
    """
    def __init__(self, stream):
        self._stream = stream
        self.total_bytes_read = 0
        self._chunk_state = None
        self.order_validator = ChunkOrderParser()

    def __iter__(self):
        """
        Process the stream and produce chunk tokens.

        Yields in order one :class:`models.ChunkHeadToken` instance,
        zero or more :class:`models.ChunkDataPartToken` instances,
        then one :class:`models.ChunkEndToken` instance, then
        repeats for the next chunk.

        """
        self._validate_signature()
        while True:
            # First read a single byte to detect EOF
            try:
                initial = self._read(1)
            except exc.UnexpectedEOF:
                # If EOF happens here, the stream ended properly at the end
                # of the last chunk so we break...
                break

            head = self._get_chunk_head(initial)
            self.order_validator.validate(head.code)
            yield head
            while self._chunk_state.next_read > 0:
                yield self._get_chunk_data()
            end = self._get_chunk_end()
            if not end.crc32ok:
                fmt = 'CRC32 check failed for {code} after {nbytes} bytes read'
                raise exceptions.BadCRC(fmt.format(
                    code=head.code,
                    nbytes=self.total_bytes_read,
                ))
            yield end

        # ...and ensure the last chunk was the IEND.
        self.order_validator.validate_end()

    def _validate_signature(self):
        header = self._read(len(PNG_SIGNATURE))
        if header != PNG_SIGNATURE:
            raise exc.SignatureMismatch(
                "Expected {expected!r}, got {actual!r}".format(
                    expected=PNG_SIGNATURE,
                    actual=header
                )
            )

    def _get_chunk_head(self, prepend_byte):
        """
        Interpret the next 8 bytes in the stream as a chunk's
        length and code, validate them, and reset the state.

        :param prepend_byte: The first byte of the chunk length field
        :type prepend_byte: bytes

        :return: The chunk length, type code, and starting position
        :rtype: tuple of (int, bytes, int)
        """
        if self._chunk_state is not None:
            raise exc.StreamStateError(
                "Must finish last chunk before starting another"
            )
        # One byte has already been read by this chunk, so don't add
        # another to the count.
        start_position = self.total_bytes_read
        [length] = struct.unpack('>I', prepend_byte + self._read(3))
        if length > PNG_MAX_CHUNK_LENGTH:
            fmt = (
                "Chunk claims to be {actual} bytes long, must be "
                "no longer than {max}."
            )
            raise exc.PNGSyntaxError(fmt.format(
                actual=length,
                max=PNG_MAX_CHUNK_LENGTH
            ))
        type_code = self._read(4)
        if not models.PNG_CHUNK_TYPE_CODE_ALLOWED_BYTES.issuperset(type_code):
            raise exc.PNGSyntaxError(
                "Invalid type code for chunk at byte {position}".format(
                    position=start_position,
                )
            )
        head = models.ChunkHeadToken(length, type_code, start_position)
        self._chunk_state = _SingleChunkState(head)
        return head

    def _get_chunk_data(self):
        """
        Read N bytes of chunk data, where N is the ``next_read``
        amount from :attr:`chunk_state`, update the chunk state, and
        return the chunk data part.

        :rtype: :class:`models.ChunkDataPartToken`
        """
        if self._chunk_state is None or self._chunk_state.next_read == 0:
            raise exc.StreamStateError(
                "Incorrect chunk state for reading data"
            )
        data = self._read(self._chunk_state.next_read)
        self._chunk_state.update(data)
        return models.ChunkDataPartToken(self._chunk_state.head, data)

    def _get_chunk_end(self):
        """
        Interpret the next 4 bytes in the stream as the chunk's
        CRC32 checksum, check if it matches the calculated checksum,
        and wipe the state.

        :rtype: :class:`models.ChunkEndToken`
        """
        if self._chunk_state is None or self._chunk_state.next_read != 0:
            raise exc.StreamStateError(
                "Incorrect chunk state for ending data"
            )

        [declared_crc32] = struct.unpack('>I', self._read(4))
        crc32okay = declared_crc32 == self._chunk_state.crc32
        rval = models.ChunkEndToken(self._chunk_state.head, crc32okay)
        self._chunk_state = None
        return rval

    def _read(self, length):
        """
        Read ``length`` bytes from the stream, update
        :ivar:`total_bytes_read`, and return the bytes.

        If the read results in fewer bytes than requested, raise
        :exc:`exceptions.UnexpectedEOF`.
        """
        if length + self.total_bytes_read > PNG_MAX_FILE_SIZE:
            raise exc.PNGTooLarge(
                "Attempted to read past file size limit: {size} bytes".format(
                    size=PNG_MAX_FILE_SIZE,
                )
            )
        data = self._stream.read(length)
        actual = len(data)
        self.total_bytes_read += actual
        assert length >= actual, "Read more bytes than requested"
        if length > actual:
            fmt = "Expected to read {length}, got {actual}, total read {total}"
            raise exc.UnexpectedEOF(fmt.format(
                length=length,
                actual=actual,
                total=self.total_bytes_read
            ))
        return data


class _SingleChunkState(object):
    """
    Represents the state of processing of a single chunk into tokens.

    No attribute may be modified externally.

    :ivar head:
        The chunk's header: total length of the chunk data, type code,
        and the position in the stream where the chunk started
    :type head: :class:`models.ChunkHeadToken`
    :ivar data_remaining:
        The number of chunk data bytes not yet processed
    :type data_remaining: int
    :ivar crc32: The running crc32 checksum
    :type crc32: int
    :ivar next_read:
        The number of bytes for the :class:`ChunkTokenStream` to
        provide to the next call of this instance's `update` method.
    :type next_read: int

    """

    # Maximum number of bytes of chunk data processed at one time. This implies
    # that the largest amount of data in a :class:`models.ChunkDataPartToken`
    # instance is somewhat less than this value.   This must never be less than
    # the length of the largest chunk with a defined  maximum length, including
    # chunk header and checksum. In PNG 1.2, this is for  the PLTE chunk, which
    # can be up to 780 bytes long:  4 (length field) + 4 (chunk code) + 768
    # (data field) + 4 (checksum)
    PNG_CHUNK_MAX_DATA_READ = 4 * 2**10  # 4 KiB

    def __init__(self, head):
        self.head = head
        self.data_remaining = self.head.length
        self.crc32 = zlib.crc32(self.head.code)
        self._update_next_read()

    def update(self, data):
        """
        Update the state with the provided data, which must be
        :attr:`next_read` bytes long.
        """
        if len(data) != self.next_read:
            fmt = "Got {actual} bytes but expected {expected}"
            raise ValueError(fmt.format(
                actual=len(data),
                expected=self.next_read
            ))
        assert self.data_remaining >= self.next_read
        self.data_remaining -= self.next_read
        self._update_next_read()
        self.crc32 = zlib.crc32(data, self.crc32)

    def _update_next_read(self):
        self.next_read = min(self.PNG_CHUNK_MAX_DATA_READ, self.data_remaining)