# pylint: disable=redefined-outer-name,no-self-use
import pytest


@pytest.fixture
def chunk_order_parser():
    from pngdoctor.chunk_order_parser import ChunkOrderParser
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
        # TODO: Add lots more here
    ])
    def test_last_chunk_code_errors(self, chunk_codes, chunk_order_parser):
        """
        Ensure that the last provided code provokes an error.
        """
        from pngdoctor.exceptions import PNGSyntaxError
        for chunk_code in chunk_codes[:-1]:
            chunk_order_parser.validate(chunk_code)
        with pytest.raises(PNGSyntaxError):
            chunk_order_parser.validate(chunk_codes[-1])

    @pytest.mark.parametrize('non_header_code', [
        b'PLTE', b'IDAT', b'IEND', b'cHRM', b'gAMA', b'iCCP', b'sBIT', b'sRGB',
        b'bKGD', b'hIST', b'tRNS', b'pHYs', b'sPLT', b'tIME', b'iTXt', b'tEXt',
        b'zTXt', b'ukwn',
    ])
    def test_validate_only_header_allowed_first(self, non_header_code,
                                                chunk_order_parser):
        from pngdoctor.exceptions import PNGSyntaxError
        with pytest.raises(PNGSyntaxError):
            chunk_order_parser.validate(non_header_code)

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


@pytest.fixture
def chunk_count_validator():
    from pngdoctor.chunk_order_parser import _ChunkCountValidator
    return _ChunkCountValidator()


class TestChunkCountValidator:
    @pytest.mark.parametrize('chunk_code', [
        b'IDAT', b'sPLT', b'iTXt', b'tEXt', b'zTXt',
        # Unknown chunks must be allowed multiple times
        b'ukwn',
    ])
    def test_multiple_allowed(self, chunk_code, chunk_count_validator):
        chunk_count_validator.check(chunk_code)
        chunk_count_validator.check(chunk_code)
        chunk_count_validator.check(chunk_code)

    @pytest.mark.parametrize('chunk_code', [
        b'IHDR', b'PLTE', b'IEND',
        b'cHRM', b'gAMA', b'iCCP', b'sBIT', b'sRGB',
        b'bKGD', b'hIST', b'tRNS', b'pHYs', b'tIME',
    ])
    def test_error_on_nomultiple_allowed(self, chunk_code,
                                         chunk_count_validator):
        from pngdoctor.exceptions import PNGSyntaxError
        chunk_count_validator.check(chunk_code)
        with pytest.raises(PNGSyntaxError):
            chunk_count_validator.check(chunk_code)

# TODO: Add tests for _ChunkOrderStateTransitionMap
