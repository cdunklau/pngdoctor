# pylint: disable=no-self-use

def png_chunk_type(type_name):
    from pngdoctor.models import ChunkType

    return ChunkType(type_name)


class TestChunkType:
    def test_property_bit(self):
        chunk_type = png_chunk_type(b'bLOb')
        assert chunk_type.ancillary is True
        assert chunk_type.private is False
        assert chunk_type.reserved is False
        assert chunk_type.safe_to_copy is True
