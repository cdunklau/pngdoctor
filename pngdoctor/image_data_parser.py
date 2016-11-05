import abc
import itertools
import zlib

from pngdoctor import exceptions
from pngdoctor import fieldvalues


class ImageDataStreamParser:
    def __init__(self, image_header):
        if (
                image_header.compression_method ==
                fieldvalues.CompressionMethod.deflate32k
            ):
            self._decompressor = _Deflate32KDecompressor()
        else:
            msg = "Compression method {0} is not supported".format(
                image_header.compression_method)
            raise exceptions.UnsupportedField(msg)

        if (
                image_header.interlace_method ==
                fieldvalues.InterlaceMethod.none
            ):
            self._locator = _no_deinterlace_pixel_coordinates(
                image_header.width, image_header.height)
        elif (
                image_header.interlace_method ==
                fieldvalues.InterlaceMethod.adam7
            ):
            # pylint: disable=redefined-variable-type
            self._locator = _adam7_deinterlace_pixel_coordinates(
                image_header.width, image_header.height)
        else:
            msg = "Interlace method {0} is not supported".format(
                image_header.interlace_method)
            raise exceptions.UnsupportedField(msg)

        if (
                image_header.filter_method ==
                fieldvalues.FilterMethod.adaptive_five_basic
            ):
            self._unfilterer = _AdaptiveFiveBasicUnfilterer()
        else:
            msg = "Filter method {0} is not supported".format(
                image_header.filter_method)
            raise exceptions.UnsupportedField(msg)


class _Deflate32KDecompressor:
    def __init__(self):
        self._decompressor = zlib.decompressobj(wbits=15)  # window size 32768
        self._last_unconsumed = b''

    def decompress(self, data, max_length):
        result = self._decompressor.decompress(
            self._last_unconsumed + data,
            max_length
        )
        self._last_unconsumed = self._decompressor.unconsumed_tail
        return result

    def verify_end(self):
        if self._last_unconsumed or not self._decompressor.eof:
            raise exceptions.DecompressionNotFinished()
        if self._decompressor.unused_data:
            raise exceptions.DecompressionFinishedEarly()


class _AbstractPixelLocator(metaclass=abc.ABCMeta):
    def __init__(self, width, height):
        self.width = width
        self.height = height

    @abc.abstractmethod
    def __iter__(self):
        """
        Yield tuples of pixel coordinates in the order they will
        arrive in the stream.

        Coordinates start with zero. The first element of each tuple
        is the x value (width offset from the leftmost pixel), the
        second is the y value (height offset from the topmost pixel)
        which happens to be the scanline number (again zero indexed).
        """


def _no_deinterlace_pixel_coordinates(width, height):
    """Pixel locator for non-interlaced images"""
    return itertools.product(range(width), range(height))



def _adam7_deinterlace_pixel_coordinates(width, height):
    """Pixel locator for images interlaced with Adam7"""
    # This is the grid pattern overlayed over the image to perform
    # Adam7 interlacing.
    #
    #  1 6 4 6 2 6 4 6
    #  7 7 7 7 7 7 7 7
    #  5 6 5 6 5 6 5 6
    #  7 7 7 7 7 7 7 7
    #  3 6 4 6 3 6 4 6
    #  7 7 7 7 7 7 7 7
    #  5 6 5 6 5 6 5 6
    #  7 7 7 7 7 7 7 7
    #

    assert width > 0 and height > 0
    # Pass 1
    yield from itertools.product(range(0, width, 8), range(0, height, 8))
    # Pass 2
    yield from itertools.product(range(4, width, 8), range(0, height, 8))
    # Pass 3
    yield from itertools.product(range(0, width, 4), range(4, height, 8))
    # Pass 4
    yield from itertools.product(range(2, width, 4), range(0, height, 4))
    # Pass 5
    yield from itertools.product(range(0, width, 2), range(2, height, 4))
    # Pass 6
    yield from itertools.product(range(1, width, 2), range(0, height, 2))
    # Pass 7
    yield from itertools.product(range(0, width, 1), range(1, height, 2))


class _AdaptiveFiveBasicUnfilterer:
    #TODO figure out this API and implementation
    pass
