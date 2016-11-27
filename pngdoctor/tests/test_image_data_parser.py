# pylint: disable=redefined-outer-name,no-self-use
import itertools
import zlib

import pytest


@pytest.fixture
def decompressor():
    from pngdoctor.image_data_parser import _Deflate32KDecompressor
    return _Deflate32KDecompressor()


TESTDATA = b'DEADBEEF'
TESTDATA_COMPRESSED = zlib.compress(TESTDATA)


class TestDeflate32KDecompressor:
    def test_decompress_valid(self, decompressor):
        assert (
            decompressor.decompress(TESTDATA_COMPRESSED, len(TESTDATA)) ==
            TESTDATA
        )
        decompressor.verify_end()

    def test_error_on_remaining_data(self, decompressor):
        from pngdoctor.exceptions import DecompressionFinishedEarly
        extra_data = TESTDATA_COMPRESSED + b'extra'
        assert (
            decompressor.decompress(extra_data, len(TESTDATA)) ==
            TESTDATA
        )
        with pytest.raises(DecompressionFinishedEarly):
            decompressor.verify_end()

    def test_error_on_incomplete_decompression(self, decompressor):
        from pngdoctor.exceptions import DecompressionNotFinished
        target_bytes = len(TESTDATA) // 2
        assert (
            decompressor.decompress(TESTDATA_COMPRESSED, target_bytes) ==
            TESTDATA[:target_bytes]
        )
        with pytest.raises(DecompressionNotFinished):
            decompressor.verify_end()


def adam7locator(width, height):
    from pngdoctor.image_data_parser import (
        _adam7_deinterlace_pixel_coordinates
    )
    return _adam7_deinterlace_pixel_coordinates(width, height)


ADAM7_INTERLACE_PASSGRID = (
    (1, 6, 4, 6, 2, 6, 4, 6),
    (7, 7, 7, 7, 7, 7, 7, 7),
    (5, 6, 5, 6, 5, 6, 5, 6),
    (7, 7, 7, 7, 7, 7, 7, 7),
    (3, 6, 4, 6, 3, 6, 4, 6),
    (7, 7, 7, 7, 7, 7, 7, 7),
    (5, 6, 5, 6, 5, 6, 5, 6),
    (7, 7, 7, 7, 7, 7, 7, 7),
)

def create_expected_deinterlaced_pixel_order(width, height):
    """
    Return a list of tuples containing (pass number, xcoord, ycoord)
    in the order they would be returned from the deinterlacing step.

    This is constructed from the grid in the standard.
    """
    scanlines = itertools.islice(
        itertools.cycle(ADAM7_INTERLACE_PASSGRID), height)
    pass_x_y = []
    for ycoord, scanline in enumerate(scanlines):
        pass_numbers = itertools.islice(itertools.cycle(scanline), width)
        for xcoord, pass_number in enumerate(pass_numbers):
            pass_x_y.append((pass_number, xcoord, ycoord))
    pass_x_y.sort()  # sort first by pass number, then x coord, then y coord
    return pass_x_y


class TestAdam7DeinterlaceLocator:

    @pytest.mark.parametrize('width,height', [
        # Square
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        (5, 5),
        (6, 6),
        (7, 7),
        (8, 8),
        (11, 11),
        (16, 16),
        (31, 31),
        # Rectangular
        (4, 7),
        (7, 4),
        (11, 19),
        (19, 11),
    ])
    def test_from_constructed_grid(self, width, height):
        pass_x_y = create_expected_deinterlaced_pixel_order(width, height)
        actual = list(adam7locator(width, height))
        expected = [(x, y) for _, x, y in pass_x_y]
        assert actual == expected

    @pytest.mark.parametrize('width,height,expected', [
        # Single pixel
        (1, 1, [(0, 0)]),
        # Single row of pixels
        (2, 1, [(x, 0) for x in (0, 1)]),
        (3, 1, [(x, 0) for x in (0, 2, 1)]),
        (4, 1, [(x, 0) for x in (0, 2, 1, 3)]),
        (5, 1, [(x, 0) for x in (0, 4, 2, 1, 3)]),
        (6, 1, [(x, 0) for x in (0, 4, 2, 1, 3, 5)]),
        (7, 1, [(x, 0) for x in (0, 4, 2, 6, 1, 3, 5)]),
        (8, 1, [(x, 0) for x in (0, 4, 2, 6, 1, 3, 5, 7)]),
        (9, 1, [(x, 0) for x in (0, 8, 4, 2, 6, 1, 3, 5, 7)]),
        (10, 1, [(x, 0) for x in (0, 8, 4, 2, 6, 1, 3, 5, 7, 9)]),
        # Single column of pixels
        (1, 2, [(0, y) for y in (0, 1)]),
        (1, 3, [(0, y) for y in (0, 2, 1)]),
        (1, 4, [(0, y) for y in (0, 2, 1, 3)]),
        (1, 5, [(0, y) for y in (0, 4, 2, 1, 3)]),
        (1, 6, [(0, y) for y in (0, 4, 2, 1, 3, 5)]),
        (1, 7, [(0, y) for y in (0, 4, 2, 6, 1, 3, 5)]),
        (1, 8, [(0, y) for y in (0, 4, 2, 6, 1, 3, 5, 7)]),
        (1, 9, [(0, y) for y in (0, 8, 4, 2, 6, 1, 3, 5, 7)]),
        (1, 10, [(0, y) for y in (0, 8, 4, 2, 6, 1, 3, 5, 7, 9)]),
    ])
    def test_expected_coordinates(self, width, height, expected):
        assert list(adam7locator(width, height)) == expected
