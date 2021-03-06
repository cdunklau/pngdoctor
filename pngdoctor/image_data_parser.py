import abc
import itertools
import math
import zlib

from pngdoctor import exceptions
from pngdoctor import fieldvalues


class ImageDataStreamParser:
    """
    Parser for IDAT data stream.
    """
    def __init__(self, decompressor, locator, subimage_unfilterer_factory):
        self._decompressor = decompressor
        self._locator = locator
        self._subimage_unfilterer_factory = subimage_unfilterer_factory

    @classmethod
    def from_image_header(cls, image_header):
        if (
                image_header.compression_method is
                fieldvalues.CompressionMethod.deflate32k
            ):
            decompressor = _Deflate32KDecompressor()
        else:
            msg = "Compression method {0} is not supported".format(
                image_header.compression_method)
            raise exceptions.UnsupportedField(msg)

        if (
                image_header.interlace_method is
                fieldvalues.InterlaceMethod.none
            ):
            locator = _no_deinterlace_pixel_coordinates(
                image_header.width, image_header.height)
        elif (
                image_header.interlace_method is
                fieldvalues.InterlaceMethod.adam7
            ):
            # pylint: disable=redefined-variable-type
            locator = _adam7_deinterlace_pixel_coordinates(
                image_header.width, image_header.height)
        else:
            msg = "Interlace method {0} is not supported".format(
                image_header.interlace_method)
            raise exceptions.UnsupportedField(msg)

        if (
                image_header.filter_method is
                fieldvalues.FilterMethod.adaptive_five_basic
            ):
            def subimage_unfilterer_factory():
                return _AdaptiveFiveBasicSubimageUnfilterer(
                    image_header.color_type,
                    image_header.bit_depth
                )
        else:
            msg = "Filter method {0} is not supported".format(
                image_header.filter_method)
            raise exceptions.UnsupportedField(msg)

        return cls(decompressor, locator, subimage_unfilterer_factory)


class _Deflate32KDecompressor:
    def __init__(self):
        self._decompressor = zlib.decompressobj(wbits=15)  # window size 32768
        self._last_unconsumed = b''
        self.decompressed = 0

    def decompress(self, data, max_length):
        result = self._decompressor.decompress(
            self._last_unconsumed + data,
            max_length
        )
        self._last_unconsumed = self._decompressor.unconsumed_tail
        self.decompressed += len(result)
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
        For each subimage, yield out one pixel locator generator. Each
        locator generator produces pixel coordinates (tuples of x, y)
        in the order the pixels will arrive in the stream.

        Coordinates start with zero. The first element of each tuple
        is the x value (width offset from the leftmost pixel), the
        second is the y value (height offset from the topmost pixel)
        which happens to be the scanline number (again zero indexed).
        """


def _no_deinterlace_pixel_coordinates(width, height):
    """Pixel locator for non-interlaced images"""
    yield itertools.product(range(width), range(height))


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
    yield itertools.product(range(0, width, 8), range(0, height, 8))
    # Pass 2
    yield itertools.product(range(4, width, 8), range(0, height, 8))
    # Pass 3
    yield itertools.product(range(0, width, 4), range(4, height, 8))
    # Pass 4
    yield itertools.product(range(2, width, 4), range(0, height, 4))
    # Pass 5
    yield itertools.product(range(0, width, 2), range(2, height, 4))
    # Pass 6
    yield itertools.product(range(1, width, 2), range(0, height, 2))
    # Pass 7
    yield itertools.product(range(0, width, 1), range(1, height, 2))


def _calculate_bits_per_pixel(color_type, bit_depth):
    samples_per_pixel = {
        fieldvalues.ColorType.grayscale: 1,
        fieldvalues.ColorType.rgb: 3,
        fieldvalues.ColorType.indexed: 3,
        fieldvalues.ColorType.grayscale_alpha: 2,
        fieldvalues.ColorType.rgb_alpha: 4
    }
    return samples_per_pixel[color_type] * bit_depth


def _calculate_scanline_sizes(width, height, color_type, bit_depth,
                              interlace_method):
    """
    Yield the size in bytes of each scanline
    """
    bits_per_pixel = _calculate_bits_per_pixel(color_type, bit_depth)
    if interlace_method is fieldvalues.InterlaceMethod.none:
        scanline_pixel_data_length = math.ceil(width * bits_per_pixel / 8)
        # Each scanline is 1 filter-type byte followed by the pixel data
        yield from itertools.repeat(1 + scanline_pixel_data_length, height)
    elif interlace_method is fieldvalues.InterlaceMethod.adam7:
        # Pass 1
        yield from itertools.repeat(1 + math.ceil(width / 8),
                                    math.ceil(height / 8))
        # Pass 2
        yield from itertools.repeat(1 + math.ceil(max(width - 4, 0) / 8),
                                    math.ceil(height / 8))
        # Pass 3
        yield from itertools.repeat(1 + math.ceil(max(width - 4, 0) / 8),
                                    math.ceil(height / 4))
        # Pass 3
        yield from itertools.repeat(1 + math.ceil(width / 4),
                                    math.ceil(max(height - 4, 0) / 4))
        # Pass 4
        yield from itertools.repeat(1 + math.ceil(max(width - 2, 0) / 4),
                                    math.ceil(height / 4))
        # Pass 5
        yield from itertools.repeat(1 + math.ceil(width / 2),
                                    math.ceil(max(height - 2, 0) / 4))
        # Pass 6
        yield from itertools.repeat(1 + math.ceil(max(width - 1, 0) / 2),
                                    math.ceil(height / 2))
        # Pass 7
        yield from itertools.repeat(1 + width,
                                    math.ceil(max(height - 1, 0) / 2))
    else:
        msg = "Interlace method {0} is not supported".format(interlace_method)
        raise exceptions.UnsupportedField(msg)


class _AdaptiveFiveBasicSubimageUnfilterer:
    """
    Reverses the "Adaptive filtering with five basic filter types"
    filter method for a single subimage.

    For non-interlaced images, the entire image is a single subimage,
    otherwise a new instance must be used for each interlacing pass.
    """
    def __init__(self, color_type, bit_depth):
        self._color_type = color_type
        self._bit_depth = bit_depth
        self._bytes_per_pixel = math.ceil(_calculate_bits_per_pixel(
            color_type, bit_depth) / 8)
        # Scanline data does not include the filter type byte.
        self._last_scanline_data = None
        self._scanline_data_length = None

    def unfilter_scanline(self, scanline):
        """
        Given the bytes of a complete scanline from the decompressed
        image data, return a list of sample tuples.

        For indexed color, the tuples will contain only one sample
        value, this is the palette index.
        """
        if self._last_scanline_data is None:
            self._last_scanline_data = '\x00' * (len(scanline) - 1)
        else:
            if len(scanline) - 1 != len(self._last_scanline_data):
                fmt = (
                    "Input scanline length {0} does not match "
                    "last scanline length {1}"
                )
                raise exceptions.ParserStateError(fmt.format(
                    len(scanline),
                    len(self._last_scanline_data) + 1,
                ))

        filter_method = self._get_valid_filter_method(scanline[0])
        scanline_data = scanline[1:]
        unfilter = getattr(self, '_unfilter_with_method_' + filter_method.name)
        unfiltered_scanline = unfilter(scanline_data)
        self._last_scanline_data = unfiltered_scanline
        return unfiltered_scanline

    def _get_valid_filter_method(self, value):
        # pylint: disable=no-member,no-self-use
        valids = fieldvalues.AdaptiveFilterType.__members__.values()
        # pylint: enable=no-member
        if value not in valids:
            fmt = "Invalid filter type {value!r} in image data"
            raise exceptions.PNGSyntaxError(fmt.format(value=value))
        return fieldvalues.AdaptiveFilterType(value)

    def _unfilter_with_method_none(self, scanline_data):
        # pylint: disable=no-self-use
        return scanline_data

    def _unfilter_with_method_sub(self, scanline_data):
        # TODO This needs tests
        decoded_scanline_bytes = bytearray()
        for pos, filtered_byte in enumerate(scanline_data):
            offset = pos - self._bytes_per_pixel
            if offset < 0:
                prior = 0
            else:
                prior = decoded_scanline_bytes[offset]
            decoded_scanline_bytes.append((filtered_byte + prior) % 256)
        return bytes(decoded_scanline_bytes)

    def _unfilter_with_method_up(self, scanline_data):
        decoded_scanline_bytes = bytearray()
        for pos, filtered_byte in enumerate(scanline_data):
            prior = self._last_scanline_data[pos]
            decoded_scanline_bytes.append(
                (filtered_byte + prior) % 256
            )
        return bytes(decoded_scanline_bytes)

    def _unfilter_with_method_average(self, scanline_data):
        decoded_scanline_bytes = bytearray()
        for pos, filtered_byte in enumerate(scanline_data):
            prior = self._last_scanline_data[pos]
            offset = pos - self._bytes_per_pixel
            if offset < 0:
                raw = 0
            else:
                raw = decoded_scanline_bytes[pos]
            decoded_scanline_bytes.append(
                (filtered_byte + (raw + prior) // 2) % 256
            )
        return bytes(decoded_scanline_bytes)

    def _unfilter_with_method_paeth(self, scanline_data):
        decoded_scanline_bytes = bytearray()
        for pos, filtered_byte in enumerate(scanline_data):
            prior = self._last_scanline_data[pos]
            offset = pos - self._bytes_per_pixel
            if offset < 0:
                raw = prior_off = 0
            else:
                raw = decoded_scanline_bytes[offset]
                prior_off = self._last_scanline_data[offset]
            decoded_scanline_bytes.append(
                (filtered_byte + paeth_predictor(raw, prior, prior_off)) % 256
            )
        return bytes(decoded_scanline_bytes)


def paeth_predictor(left, above, upperleft):
    # a = left, b = above, c = upper left
    predict = left + above - upperleft  # initial estimate
    predict_left = abs(predict - left)  # distances to a, b, c
    predict_above = abs(predict - above)
    predict_upperleft = abs(predict - upperleft)
    # Return nearest of a, b, c, breaking ties in order a, b, c
    if predict_left <= predict_above and predict_left <= predict_upperleft:
        return left
    elif predict_above <= predict_upperleft:
        return above
    else:
        return upperleft
