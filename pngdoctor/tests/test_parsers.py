import pytest


@pytest.fixture
def chunk_order_parser():
    from pngdoctor.parsers import ChunkOrderParser
    return ChunkOrderParser()


class TestChunkOrderParser(object):
    @pytest.mark.parametrize('chunk_codes', [
        [b'IHDR', b'IDAT', b'IEND'],
        [b'IHDR', b'PLTE', b'IDAT', b'IEND'],
        # TODO: Add lots more here
    ])
    def test_valid_ordering(self, chunk_codes, chunk_order_parser):
        for chunk_code in chunk_codes:
            chunk_order_parser.validate(chunk_code)
        chunk_order_parser.validate_end()


    @pytest.mark.parametrize('chunk_codes', [
        [b'IHDR', b'IDAT', b'IEND', b'IDAT'],
        [b'IHDR', b'PLTE', b'IEND'],
        [b'ukwn'],  # Unknown chunk not allowed first
        # TODO: Add lots more here
    ])
    def test_last_chunk_code_errors(self, chunk_codes, chunk_order_parser):
        from pngdoctor.exceptions import PNGSyntaxError
        for chunk_code in chunk_codes[:-1]:
            chunk_order_parser.validate(chunk_code)
        with pytest.raises(PNGSyntaxError):
            chunk_order_parser.validate(chunk_codes[-1])


    def test_validate_header_must_be_first(self, chunk_order_parser):
        from pngdoctor.exceptions import PNGSyntaxError
        chunk_code = b'PLTE'
        with pytest.raises(PNGSyntaxError):
            chunk_order_parser.validate(chunk_code)


    def test_validate_end_errors_when_not_finished(self, chunk_order_parser):
        from pngdoctor.exceptions import PNGSyntaxError
        for chunk_code in [b'IHDR', b'IDAT']:  # No end
            chunk_order_parser.validate(chunk_code)
        with pytest.raises(PNGSyntaxError):
            chunk_order_parser.validate_end()


    @pytest.mark.parametrize('chunk_codes', [
        [b'IHDR', b'ukwn', b'PLTE', b'IDAT', b'IEND'],
        [b'IHDR', b'PLTE', b'ukwn', b'IDAT', b'IEND'],
        [b'IHDR', b'PLTE', b'IDAT', b'ukwn', b'IEND'],
        [b'IHDR', b'ukwn', b'IDAT', b'ukwn', b'IEND'],
        [b'IHDR', b'ukwn', b'IDAT', b'IEND'],
    ])
    def test_unknown_chunks_valid(self, chunk_codes, chunk_order_parser):
        for chunk_code in chunk_codes:
            chunk_order_parser.validate(chunk_code)
        chunk_order_parser.validate_end()