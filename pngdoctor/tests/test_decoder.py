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


def chunk_token_stream_with_bytes(stream_bytes):
    from pngdoctor.decoder import PNGChunkTokenStream

    return PNGChunkTokenStream(io.BytesIO(stream_bytes))


def chunk_tokens_from_fakes(chunk_fakes):
    # This does not allow for multiple data tokens or bad CRC
    from pngdoctor.decoder import PNG_SIGNATURE
    from pngdoctor.models import (
        PNGChunkHeadToken, PNGChunkDataPartToken, PNGChunkEndToken
    )
    tokens = []
    position = 1 + len(PNG_SIGNATURE)
    for fake in chunk_fakes:
        head_token = PNGChunkHeadToken(fake.length, fake.type, position)
        tokens.append(head_token)
        if fake.data:
            tokens.append(PNGChunkDataPartToken(head_token, fake.data))
        tokens.append(PNGChunkEndToken(head_token, True))
        position += len(fake.bytes_with_crc32)
    return tokens


class TestPNGChunkTokenStream:
    def test_iter(self):
        from pngdoctor.decoder import PNG_SIGNATURE

        contents = b''.join([
            PNG_SIGNATURE,
            ihdr_one_by_one_rgb24.bytes_with_crc32,
            idat_onepix_4488cc.bytes_with_crc32,
            iend.bytes_with_crc32
        ])
        chunk_token_stream = chunk_token_stream_with_bytes(contents)

        expected_tokens = chunk_tokens_from_fakes([
            ihdr_one_by_one_rgb24,
            idat_onepix_4488cc,
            iend
        ])

        actual_tokens = list(chunk_token_stream)

        assert actual_tokens == expected_tokens

    def test_iter_if_IHDR_not_first(self):
        from pngdoctor.decoder import PNG_SIGNATURE
        from pngdoctor.exceptions import PNGSyntaxError

        contents = b''.join([PNG_SIGNATURE, iend.bytes_with_crc32])
        chunk_token_stream = chunk_token_stream_with_bytes(contents)
        with pytest.raises(PNGSyntaxError) as excinfo:
            next(iter(chunk_token_stream))
        assert "Chunk b'IEND' is not allowed here" in str(excinfo.value)

    def test_iter_fails_on_EOF_after_IEND(self):
        from pngdoctor.decoder import PNG_SIGNATURE
        from pngdoctor.exceptions import PNGSyntaxError

        contents = b''.join([
            PNG_SIGNATURE,
            ihdr_one_by_one_rgb24.bytes_with_crc32,
            iend.bytes_with_crc32,
            b'extra'
        ])
        chunk_token_stream = chunk_token_stream_with_bytes(contents)
        with pytest.raises(PNGSyntaxError) as excinfo:
            for chunk in chunk_token_stream:
                pass
        assert "Chunk b'IEND' is not allowed here" in str(excinfo.value)

    def test__read(self):
        from pngdoctor.exceptions import UnexpectedEOF

        chunk_token_stream = chunk_token_stream_with_bytes(b'1234')
        assert chunk_token_stream._read(2) == b'12'
        assert chunk_token_stream.total_bytes_read == 2
        assert chunk_token_stream._read(2) == b'34'
        assert chunk_token_stream.total_bytes_read == 4
        with pytest.raises(UnexpectedEOF):
            chunk_token_stream._read(1)

    def test__read__fails_if_file_too_large(self):
        from pngdoctor.exceptions import PNGTooLarge

        chunk_token_stream = chunk_token_stream_with_bytes(b'1234')
        chunk_token_stream.total_bytes_read = 20 * 2**20
        with pytest.raises(PNGTooLarge):
            chunk_token_stream._read(4)

    def test__read__fails_if_eof_reached(self):
        from pngdoctor.exceptions import UnexpectedEOF

        chunk_token_stream = chunk_token_stream_with_bytes(b'1234')
        chunk_token_stream._read(3)
        with pytest.raises(UnexpectedEOF) as excinfo:
            chunk_token_stream._read(2)
        assert re.match(
            r"Expected to read 2, got 1, total read 4\b",
            str(excinfo.value)
        ) is not None

    def test__validate_signature(self):
        from pngdoctor.decoder import PNG_SIGNATURE

        chunk_token_stream = chunk_token_stream_with_bytes(PNG_SIGNATURE)
        chunk_token_stream._validate_signature()
        assert chunk_token_stream.total_bytes_read == len(PNG_SIGNATURE)

    def test__validate_signature__errors_with_bad_signature(self):
        from pngdoctor.exceptions import SignatureMismatch

        chunk_token_stream = chunk_token_stream_with_bytes(b'123456789')
        with pytest.raises(SignatureMismatch):
            chunk_token_stream._validate_signature()

    @pytest.mark.skip
    def test__get_chunk_head(self):
        ...

    @pytest.mark.skip
    def test__get_chunk_data(self):
        ...

    @pytest.mark.skip
    def test__get_chunk_end(self):
        ...
