import inspect
import struct
import zlib
from collections import namedtuple, Counter

from pngdoctor import exceptions as exc
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
PNG_MAX_FILE_SIZE = 20 * 2**20  # 20 MiB is large enough for reasonable PNGs
PNG_MAX_CHUNK_LENGTH = 2**31 - 1  # Max length of chunk data
PNG_CHUNK_MAX_DATA_READ = 4 * 2**10  # 4 KiB max chunk data processed


class PNGChunkTokenStream(object):
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

    :ivar chunk_state: The state of the current chunk's processing
    :type chunk_state: :class:`PNGSingleChunkState`
    :ivar total_bytes_read:
        Total number of bytes consumed from the underlying file object
    :type total_bytes_read: int
    """
    def __init__(self, stream):
        self._stream = stream
        self.total_bytes_read = 0
        self.chunk_state = None
        self.order_validator = PNGChunkSequenceValidator()

    def __iter__(self):
        """
        Process the stream and produce chunk tokens.

        Yields in order one :class:`PNGChunkHeadToken` instance,
        zero or more :class:`PNGChunkDataPartToken` instances, then
        one :class:`PNGChunkEndToken` instance, then repeats for the
        next chunk.

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
            self.order_validator.validate(head)
            yield head
            while self.chunk_state.next_read > 0:
                yield self._get_chunk_data()
            end = self._get_chunk_end()
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
        if self.chunk_state is not None:
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
                    self.start_position,
                )
            )
        head = PNGChunkHeadToken(length, type_code, start_position)
        self.chunk_state = PNGSingleChunkState(head)
        return head

    def _get_chunk_data(self):
        """
        Read N bytes of chunk data, where N is the ``next_read``
        amount from :attr:`chunk_state`, update the chunk state, and
        return the chunk data part.

        :rtype: :class:`PNGChunkDataPartToken`
        """
        if self.chunk_state is None or self.chunk_state.next_read == 0:
            raise exc.StreamStateError(
                "Incorrect chunk state for reading data"
            )
        data = self._read(self.chunk_state.next_read)
        self.chunk_state.update(data)
        return PNGChunkDataPartToken(self.chunk_state.head, data)

    def _get_chunk_end(self):
        """
        Interpret the next 4 bytes in the stream as the chunk's
        CRC32 checksum, check if it matches the calculated checksum,
        and wipe the state.

        :rtype: :class:`PNGChunkEndToken`
        """
        if self.chunk_state is None or self.chunk_state.next_read != 0:
            raise exc.StreamStateError(
                "Incorrect chunk state for ending data"
            )
        
        [declared_crc32] = struct.unpack('>I', self._read(4))
        crc32okay = declared_crc32 == self.chunk_state.crc32
        rval = PNGChunkEndToken(self.chunk_state.head, crc32okay)
        self.chunk_state = None
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


class PNGChunkHeadToken(namedtuple('_Head', ['length', 'code', 'position'])):
    """
    The start of a PNG chunk.

    :ivar length: The number of bytes comprising the chunk's data
    :type length: int
    :ivar code: The PNG chunk type code
    :type code: bytes
    :ivar position: Where the chunk started in the stream
    :type position: int
    """


class PNGChunkDataPartToken(namedtuple('_DataPart', ['head', 'data'])):
    """
    A portion (or all) of the data from a PNG chunk.

    :ivar head: The head token from this chunk
    :type head: :class:`PNGChunkHeadToken`
    :ivar data: The bytes from this portion of the chunk
    :type data: bytes
    """


class PNGChunkEndToken(namedtuple('_End', ['head', 'crc32ok'])):
    """
    The end marker for a PNG chunk.

    :ivar head: The head token from this chunk
    :type head: :class:`PNGChunkHeadToken`
    :ivar crc32ok: If the CRC32 checksum validated properly
    :type crc32ok: bool
    """


class PNGSingleChunkState(object):
    """
    Represents the state of processing of a single chunk.

    No attribute may be modified externally.

    :ivar head:
        The chunk's header: total length of the chunk data, type code,
        and the position in the stream where the chunk started
    :type head: :class:`PNGChunkHeadToken`
    :ivar data_remaining:
        The number of chunk data bytes not yet processed
    :type data_remaining: int
    :ivar crc32: The running crc32 checksum
    :type crc32: int
    :ivar next_read:
        The number of bytes for the :class:`PNGChunkStream` to provide
        to the next call of this instance's `update` method.
    :type next_read: int

    """
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
        self.next_read = min(PNG_CHUNK_MAX_DATA_READ, self.data_remaining)



def chunk_handler(chunk_type):
    """
    Method decorator for chunk handlers.

    Sets an attribute on the function object so the handler dict can
    be built in :meth:`PNGChunkSequenceValidator.__init__`.

    :param chunk_type: The PNG chunk type.
    :type chunk_type: :class:`models.PNGChunkType`
    """
    if not isinstance(chunk_type, bytes):
        raise TypeError('chunk_type must be bytes')

    def decorator(method):
        method.chunk_type = chunk_type
        return method

    return decorator


def _ischunkhandler(member):
    """Predicate for inspect.getmembers"""
    return inspect.ismethod(member) and hasattr(member, 'chunk_type_code')



# TODO: rewrite this to use the things in pngdoctor.fsm
class PNGChunkSequenceValidator(object):
    """
    Tracks the chunks seen and validates their order, presence, and
    dependencies.
    """
    def __init__(self):
        # PNG chunk codes currently allowed
        self._allowed_chunk_type_codes = set([b'IHDR'])

        # This probably goes away
        self._handlers = {}
        for method in inspect.getmembers(self, _ischunkhandler):
            if method.chunk_type in self._handlers:
                fmt = 'Chunk type {type} has more than one handler.'
                raise TypeError(fmt.format(type=method.chunk_type))
            self._handlers[method.chunk_type] = method

        # The validation routine to call
        self._validate = self._validate_image_header

        self.image_header_seen = False
        self.palette_seen = False
        self.image_data_seen = False
        self.image_trailer_seen = False
        # TODO: needs more attributes

    def validate(self, chunk_head_token):
        if chunk_head_token.code not in self._allowed_chunk_type_codes:
            raise PNGSyntaxError('Bad chunk code {code}'.format(
                code=chunk_head_token.code
            ))
        chunk_type = models.CODE_TYPES.get(chunk_head_token.code)
        if chunk_type is None:
            fmt = 'Unknown chunk type code {code} at byte {pos}'
            logger.warning(fmt.format(
                code=chunk_head_token.code,
                pos=chunk_head_token.position
            ))
        handler_method = self.handlers[chunk_type]
        handler_method(chunk_head_token)
        self.seen_chunks[chunk_head_token.code] += 1

    def validate_end(self):
        """
        Called when the end of the stream is reached. Ensure that the
        image end chunk was validated or raise an exception.
        """
        if not self.image_trailer_seen:
            raise exc.PNGSyntaxError(
                'No image trailer (IEND) chunk before stream end'
            )

    @chunk_handler(models.IMAGE_HEADER)
    def _handle_image_header(self, token):
        if len(self.seen_chunks):
            raise exc.PNGSyntaxError('Image header must be first chunk')
