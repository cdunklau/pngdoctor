import itertools

import attr


PNG_CHUNK_TYPE_PROPERTY_BITMASK = 0b00100000
PNG_CHUNK_TYPE_CODE_ALLOWED_BYTES = frozenset(
    itertools.chain(range(65, 91), range(97, 123)))


_valid_bytes = attr.validators.instance_of(bytes)


def _valid_chunk_type_code(instance, attribute, value):
    _valid_bytes(instance, attribute, value)
    if len(value) != 4:
        raise ValueError("{!r} must be exactly 4 bytes long".format(attribute))
    if not PNG_CHUNK_TYPE_CODE_ALLOWED_BYTES.issuperset(value):
        raise ValueError("{!r} contains invalid bytes".format(attribute))


@attr.attributes
class ChunkType:
    code = attr.attr(validator=_valid_chunk_type_code)

    @property
    def ancillary(self):
        # pylint: disable=unsubscriptable-object
        return bool(self.code[0] & PNG_CHUNK_TYPE_PROPERTY_BITMASK)

    @property
    def private(self):
        # pylint: disable=unsubscriptable-object
        return bool(self.code[1] & PNG_CHUNK_TYPE_PROPERTY_BITMASK)

    @property
    def reserved(self):
        # pylint: disable=unsubscriptable-object
        return bool(self.code[2] & PNG_CHUNK_TYPE_PROPERTY_BITMASK)

    @property
    def safe_to_copy(self):
        # pylint: disable=unsubscriptable-object
        return bool(self.code[3] & PNG_CHUNK_TYPE_PROPERTY_BITMASK)


@attr.attributes
class ChunkHeadToken:
    """
    The start of a PNG chunk.

    :ivar length: The number of bytes comprising the chunk's data
    :type length: int
    :ivar code: The PNG chunk type code
    :type code: bytes
    :ivar position: Where the chunk started in the stream
    :type position: int
    """
    length = attr.attr()
    code = attr.attr()
    position = attr.attr()


@attr.attributes
class ChunkDataPartToken:
    """
    A portion (or all) of the data from a PNG chunk.

    :ivar head: The head token from this chunk
    :type head: :class:`ChunkHeadToken`
    :ivar data: The bytes from this portion of the chunk
    :type data: bytes
    """
    head = attr.attr()
    data = attr.attr()

    def __repr__(self):
        return '{name}(head={head!r}, data_length={length})'.format(
            name=self.__class__.__name__,
            head=self.head,
            length=len(self.data),
        )


@attr.attributes
class ChunkEndToken:
    """
    The end marker for a PNG chunk.

    :ivar head: The head token from this chunk
    :type head: :class:`ChunkHeadToken`
    :ivar crc32ok: If the CRC32 checksum validated properly
    :type crc32ok: bool
    """
    head = attr.attr()
    crc32ok = attr.attr()


@attr.attributes
class ImageHeader:
    width = attr.attr()
    height = attr.attr()
    bit_depth = attr.attr()
    color_type = attr.attr()
    compression_method = attr.attr()
    filter_method = attr.attr()
    interlace_method = attr.attr()


@attr.attributes
class Palette:
    entries = attr.attr()
