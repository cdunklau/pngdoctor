class DecodeError(Exception):
    pass


class StreamStateError(DecodeError):
    pass


class UnexpectedEOF(DecodeError):
    pass


class SignatureMismatch(DecodeError):
    pass


class BadCRC(DecodeError):
    pass


class PNGSyntaxError(DecodeError):
    pass


class PNGTooLarge(DecodeError):
    pass
