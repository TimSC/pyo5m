"""Varint and zigzag coding of numbers, as o5m uses them.

A varint stores an unsigned number in groups of seven bits, least significant
first, with the top bit of each byte set when another byte follows. Zigzag
coding maps signed numbers to unsigned ones (0, -1, 1, -2, ... to 0, 1, 2, 3,
...) so small negative numbers stay short.

These run for every number in a file, so they are written for speed: numbers
of one or two bytes, the great majority, come from a table, and up to five
bytes are unrolled. encode_zigzag repeats encode_varint rather than calling it
to save a function call."""

# A varint holds at most 64 bits, which take ten bytes of seven bits each.
# Anything longer is corrupt data.
MAX_VARINT_BYTES = 10

# The encoding of every number below 2**14, which takes one or two bytes
_SHORT = [bytes((value,)) if value < 0x80 else bytes(((value & 0x7f) | 0x80, value >> 7)) for value in range(0x4000)]

def _encode_long(value):
	if value >= 1 << 64:
		raise OverflowError("Varint value out of range")
	out = bytearray()
	while value >= 0x80:
		out.append((value & 0x7f) | 0x80)
		value >>= 7
	out.append(value)
	return bytes(out)

def encode_varint(value):
	"""Encodes an unsigned number of up to 64 bits."""
	if 0 <= value < 0x4000:
		return _SHORT[value]
	if value < 0x200000:
		if value < 0:
			raise OverflowError("Varint value out of range: {}".format(value))
		return bytes(((value & 0x7f) | 0x80, ((value >> 7) & 0x7f) | 0x80, value >> 14))
	if value < 0x10000000:
		return bytes(((value & 0x7f) | 0x80, ((value >> 7) & 0x7f) | 0x80, ((value >> 14) & 0x7f) | 0x80, value >> 21))
	if value < 0x800000000:
		return bytes(((value & 0x7f) | 0x80, ((value >> 7) & 0x7f) | 0x80, ((value >> 14) & 0x7f) | 0x80,
			((value >> 21) & 0x7f) | 0x80, value >> 28))
	return _encode_long(value)

def encode_zigzag(value):
	"""Encodes a signed number of up to 64 bits."""
	value = (value << 1) if value >= 0 else ((-value) << 1) - 1
	if value < 0x4000:
		return _SHORT[value]
	if value < 0x200000:
		return bytes(((value & 0x7f) | 0x80, ((value >> 7) & 0x7f) | 0x80, value >> 14))
	if value < 0x10000000:
		return bytes(((value & 0x7f) | 0x80, ((value >> 7) & 0x7f) | 0x80, ((value >> 14) & 0x7f) | 0x80, value >> 21))
	if value < 0x800000000:
		return bytes(((value & 0x7f) | 0x80, ((value >> 7) & 0x7f) | 0x80, ((value >> 14) & 0x7f) | 0x80,
			((value >> 21) & 0x7f) | 0x80, value >> 28))
	return _encode_long(value)

def decode_varint(data, pos=0):
	"""Decodes an unsigned varint from bytes at pos. Returns (value, next pos)."""
	try:
		byte = data[pos]
		if byte < 0x80:
			return byte, pos + 1
		total = byte & 0x7f
		shift = 7
		while True:
			pos += 1
			byte = data[pos]
			total |= (byte & 0x7f) << shift
			if byte < 0x80:
				return total & 0xffffffffffffffff, pos + 1
			shift += 7
			if shift > 63:
				raise ValueError("Varint is too long")
	except IndexError:
		raise EOFError("Input ended in the middle of a varint") from None

def decode_zigzag(data, pos=0):
	"""Decodes a signed zigzag varint from bytes at pos. Returns (value, next pos)."""
	try:
		byte = data[pos]
		if byte < 0x80:
			return (byte >> 1) ^ -(byte & 1), pos + 1
		total = byte & 0x7f
		shift = 7
		while True:
			pos += 1
			byte = data[pos]
			total |= (byte & 0x7f) << shift
			if byte < 0x80:
				total &= 0xffffffffffffffff
				return (total >> 1) ^ -(total & 1), pos + 1
			shift += 7
			if shift > 63:
				raise ValueError("Varint is too long")
	except IndexError:
		raise EOFError("Input ended in the middle of a varint") from None

def read_varint(stream):
	"""Reads an unsigned varint from a binary stream, a byte at a time."""
	total = 0
	for count in range(MAX_VARINT_BYTES):
		raw = stream.read(1)
		if len(raw) == 0:
			raise EOFError("Input ended in the middle of a varint")
		byte = raw[0]
		total |= (byte & 0x7f) << (7 * count)
		if byte < 0x80:
			return total & 0xffffffffffffffff
	raise ValueError("Varint is too long")
