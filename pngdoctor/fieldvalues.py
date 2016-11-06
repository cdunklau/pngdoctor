"""
Enumerations for easier interpretation of PNG flags and values.
"""
import enum


class ColorType(enum.Enum):
    grayscale = 0
    rgb = 2
    indexed = 3
    grayscale_alpha = 4
    rgb_alpha = 6


class CompressionMethod(enum.Enum):
    deflate32k = 0


class FilterMethod(enum.Enum):
    adaptive_five_basic = 0


class InterlaceMethod(enum.Enum):
    none = 0
    adam7 = 1
