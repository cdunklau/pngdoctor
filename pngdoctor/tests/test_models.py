
def png_chunk_type(type_name):
    from pngdoctor.models import PNGChunkType

    return PNGChunkType(type_name)


class TestPNGChunkType:
    def test_property_bit(self):
        t = png_chunk_type(b'bLOb')
        assert t.ancillary is True
        assert t.private is False
        assert t.reserved is False
        assert t.safe_to_copy is True
