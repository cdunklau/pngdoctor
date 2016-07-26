import io
import re
import struct
import zlib

import pytest



class PNGChunkFake:
    def __init__(self, type_, data):
        self.type = type_
        self.data = data

    @property
    def length(self):
        return len(self.data)

    @property
    def crc32_bytes(self):
        crc = zlib.crc32(self.type)
        crc = zlib.crc32(self.data, crc)
        return struct.pack('>I', crc)

    @property
    def bytes(self):
        b = struct.pack('>I4s', self.length, self.type)
        return b + self.data

    @property
    def bytes_with_crc32(self):
        return self.bytes + self.crc32_bytes


def test_pngchunkfake_crc32():
    expected = 0xcbf43926.to_bytes(4, "big")
    actual = PNGChunkFake(b'1234', b'56789').crc32_bytes 
    assert actual == expected


ihdr_one_by_one_rgb24 = PNGChunkFake(
    b'IHDR',
    struct.pack(
        '>IIBBBBB',
        1,  # Image width
        1,  # Image height
        8,  # Bit depth
        2,  # Color type is RGB
        0,  # Compression method is DEFLATE with 32K sliding window
        0,  # Filter method is "adaptive filtering with five basic filter
            # types"
        0,  # Interlace method is no interlace
    )
)
# Single pixel example IDAT created with GIMP (hexdump with relevant data)
#                                            00 00  |              ..|
# 00 0c 49 44 41 54 08 d7  63 70 e9 38 03 00 02 ac  |..IDAT..cp.8....|
# 01 99 cb 83 c0 90                                 |......          |
#
# Chunk bytes:
# 00 00 00 0c 49 44 41 54 08 d7 63 70 e9 38 03 00 02 ac 01 99 cb 83 c0 90
# --len 12---| I  D  A  T|------------zlib-data--------------|---crc32---|
#
# Decompressed zlib data: 00 44 88 CC
# Filter type 0 (no filtering)
# Pastel blue #4488cc
idat_onepix_4488cc = PNGChunkFake(
    b'IDAT',
    b'\x08\xd7\x63\x70\xe9\x38\x03\x00\x02\xac\x01\x99'
)

iend = PNGChunkFake(b'IEND', b'')


def test_signature_correct():
    from pngdoctor.decoder import PNG_SIGNATURE

    assert PNG_SIGNATURE == b'\x89PNG\r\n\x1A\n'


def lexer_with_bytes(stream_bytes):
    from pngdoctor.decoder import PNGLexer

    return PNGLexer(io.BytesIO(stream_bytes))


class TestPNGLexer:
    def test_iter_chunk_type_and_data(self):
        from pngdoctor.decoder import PNG_SIGNATURE

        contents = b''.join([
            PNG_SIGNATURE,
            ihdr_one_by_one_rgb24.bytes_with_crc32,
            idat_onepix_4488cc.bytes_with_crc32,
            iend.bytes_with_crc32
        ])
        lex = lexer_with_bytes(contents)
        expected_chunks = [
            (ihdr_one_by_one_rgb24.type, ihdr_one_by_one_rgb24.data),
            (idat_onepix_4488cc.type, idat_onepix_4488cc.data),
            (iend.type, iend.data)
        ]
        actual_chunks = list(lex.iter_chunk_type_and_data())
        assert actual_chunks == expected_chunks

    def test_iter_chunk_type_and_data__fails_if_IHDR_not_first(self):
        from pngdoctor.decoder import PNG_SIGNATURE
        from pngdoctor.exceptions import PNGSyntaxError

        contents = b''.join([PNG_SIGNATURE, iend.bytes_with_crc32])
        lex = lexer_with_bytes(contents)
        with pytest.raises(PNGSyntaxError) as excinfo:
            for chunk in lex.iter_chunk_type_and_data():
                pass
        assert "First chunk expected to be IHDR" in str(excinfo.value)

    def test_iter_chunk_type_and_data__fails_on_EOF_after_IEND(self):
        from pngdoctor.decoder import PNG_SIGNATURE
        from pngdoctor.exceptions import PNGSyntaxError

        contents = b''.join([
            PNG_SIGNATURE,
            ihdr_one_by_one_rgb24.bytes_with_crc32,
            iend.bytes_with_crc32,
            b'extra'
        ])
        lex = lexer_with_bytes(contents)
        with pytest.raises(PNGSyntaxError) as excinfo:
            for chunk in lex.iter_chunk_type_and_data():
                pass
        assert "Data exists beyond IEND chunk end" in str(excinfo.value)

    def test__read(self):
        from pngdoctor.exceptions import UnexpectedEOF

        lex = lexer_with_bytes(b'1234')
        assert lex._read(2) == b'12'
        assert lex._nbytes_read == 2
        assert lex._read(2) == b'34'
        assert lex._nbytes_read == 4
        with pytest.raises(UnexpectedEOF):
            lex._read(1)

    def test__read__fails_if_file_too_large(self):
        from pngdoctor.exceptions import PNGTooLarge

        lex = lexer_with_bytes(b'1234')
        lex._nbytes_read = 20 * 2**20
        with pytest.raises(PNGTooLarge):
            lex._read(4)

    def test__read__fails_if_eof_reached(self):
        from pngdoctor.exceptions import UnexpectedEOF

        lex = lexer_with_bytes(b'1234')
        lex._read(3)
        with pytest.raises(UnexpectedEOF) as excinfo:
            lex._read(2)
        assert re.match(
            r"Expected to read 2, got 1, total read 4\b",
            str(excinfo.value)
        ) is not None

    def test__validate_signature(self):
        from pngdoctor.decoder import PNG_SIGNATURE

        lex = lexer_with_bytes(PNG_SIGNATURE)
        lex._validate_signature()
        assert lex._nbytes_read == len(PNG_SIGNATURE)

    def test__validate_signature__errors_with_bad_signature(self):
        from pngdoctor.exceptions import SignatureMismatch

        lex = lexer_with_bytes(b'123456789')
        with pytest.raises(SignatureMismatch):
            lex._validate_signature()

    def test__get_next_chunk(self):
        lex = lexer_with_bytes(ihdr_one_by_one_rgb24.bytes_with_crc32)
        chunk_type, chunk_data = lex._get_next_chunk()
        assert chunk_type == b'IHDR'
        assert len(chunk_data) == 13
        assert chunk_data == ihdr_one_by_one_rgb24.data

    def test__get_next_chunk__errors_with_chunk_length_too_large(self):
        from pngdoctor.exceptions import PNGSyntaxError

        too_long = 2**31  # max is 2**31 - 1
        lex = lexer_with_bytes(too_long.to_bytes(4, 'big'))
        with pytest.raises(PNGSyntaxError):
            lex._get_next_chunk()

    def test__get_next_chunk__errors_with_wrong_crc32(self):
        from pngdoctor.exceptions import BadCRC

        bad_crc32 = b'\x00\x00\x00\x00'
        lex = lexer_with_bytes(ihdr_one_by_one_rgb24.bytes + bad_crc32)
        with pytest.raises(BadCRC):
            lex._get_next_chunk()

    def test__get_next_chunk__errors_with_corrupted_data(self):
        from pngdoctor.exceptions import BadCRC

        chuck_with_bad_data = bytearray(
            ihdr_one_by_one_rgb24.bytes_with_crc32
        )
        chuck_with_bad_data[9] = 0xff
        lex = lexer_with_bytes(chuck_with_bad_data)
        with pytest.raises(BadCRC) as excinfo:
            lex._get_next_chunk()

        assert re.match(
            r"CRC check failed for chunk starting at position 1\b",
            str(excinfo.value)
        ) is not None



