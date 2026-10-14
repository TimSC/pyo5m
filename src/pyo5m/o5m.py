"""o5m and o5c, described at https://wiki.openstreetmap.org/wiki/O5m

In an o5c (change) file an object cut short after its ID and metadata is a
delete. The decoder gives such an object meta.visible False, with no tags,
members or position, and the encoder writes any object with meta.visible
False that way."""

import math
from collections import deque

from .handler import DecodeError, Handler
from .model import Bounds, Member, MetaData, Node, Relation, Way, epoch_seconds, utc_datetime
from .varint import decode_varint, decode_zigzag, encode_varint, encode_zigzag, read_varint

NODE = 0x10
WAY = 0x11
RELATION = 0x12
BOUNDS = 0xdb
HEADER = 0xe0
SYNC = 0xee
END = 0xfe
RESET = 0xff

# Not part of the o5m standard: cppo5m's dataset for attributes of the document
# as a whole, which pyo5m reads and writes too. Its contents start with this
# marker, in case another program uses the same type for something else,
# followed by key and value strings, each ending in a zero byte. Programs that
# do not know it skip it, as the format requires, though osmconvert drops it if
# it rewrites the file.
ATTRIBUTES = 0xc0
ATTRIBUTES_MARKER = b"cppo5m-attributes\x00"

# Strings whose combined length is at most this go in the string table
REF_TABLE_LENGTH_THRESHOLD = 250
REF_TABLE_SIZE = 15000

_MEMBER_TYPE_CODES = {"node": b"0", "way": b"1", "relation": b"2"}

def wrap32(value):
	"""Wraps a number to a signed 32 bit integer."""
	value &= 0xffffffff
	return value - 0x100000000 if value >= 0x80000000 else value

def round_coord(degrees):
	"""Rounds a coordinate in degrees to o5m's units of 100 nanodegrees, half
	away from zero. Raises ValueError if it does not fit the 32 bits the
	format uses for node positions."""
	scaled = float(degrees) * 1e7
	if not math.isfinite(scaled) or abs(scaled) > 2147483647.0:
		raise ValueError("Coordinate is out of range: {}".format(degrees))
	rounded = int(math.floor(abs(scaled) + 0.5))
	return rounded if scaled >= 0 else -rounded

def _encode_string(value):
	"""UTF-8, refusing zero bytes, which o5m uses to end strings."""
	encoded = value.encode("utf-8")
	if b"\x00" in encoded:
		raise ValueError("o5m strings cannot contain a zero byte")
	return encoded

# ****** decoding ******

class O5mDecoder(object):
	"""Decodes o5m or o5c from a binary file object, sending what it finds to a
	Handler. run() decodes everything; decode_next() decodes one dataset at a
	time and returns False once the end is reached. The handler's finish is
	called at the end either way."""

	def __init__(self, source, handler, max_object_bytes=256 * 1024 * 1024):
		self.source = source
		self.handler = handler
		self.max_object_bytes = max_object_bytes
		self.is_diff = False
		self._header_read = False
		self._finished = False
		self._reset_delta_coding()

	def _reset_delta_coding(self):
		self._last_id = 0
		self._last_timestamp = 0
		self._last_changeset = 0
		self._last_lat = 0
		self._last_lon = 0
		self._last_ref = {"node": 0, "way": 0, "relation": 0}
		# The string table is a ring buffer, so a lookup costs the same however
		# full it is
		self._strings = [None] * REF_TABLE_SIZE
		self._strings_count = 0
		self._strings_next = 0

	def run(self):
		while self.decode_next():
			pass

	def decode_next(self):
		"""Decodes the next dataset. Returns False at the end of the data."""
		if self._finished:
			return False
		if not self._header_read:
			self._read_header()
			return True

		raw = self.source.read(1)
		if len(raw) == 0 or raw[0] == END:
			#A missing end marker is tolerated
			self._finished = True
			self.handler.finish()
			return False
		code = raw[0]
		if code == RESET:
			self._reset_delta_coding()
			self.handler.reset()
			return True
		if code >= 0xf0:
			return True #Other single byte codes carry no data

		data = self._read_block()
		#The data is decoded first and handed over afterwards, so exceptions
		#raised by the handler reach the caller unchanged
		try:
			if code == NODE:
				store, item = self.handler.store_node, self._decode_node(data)
			elif code == WAY:
				store, item = self.handler.store_way, self._decode_way(data)
			elif code == RELATION:
				store, item = self.handler.store_relation, self._decode_relation(data)
			elif code == BOUNDS:
				store, item = self.handler.store_bounds, self._decode_bounds(data)
			elif code == ATTRIBUTES:
				store, item = self.handler.store_attributes, self._decode_attributes(data)
				if not item:
					return True
			else:
				return True #Skip anything else, which includes sync markers and repeated headers
		except (EOFError, ValueError, IndexError) as err:
			raise DecodeError("o5m decode failed: {}".format(err)) from err
		store(item)
		return True

	def _read_header(self):
		start = self.source.read(2)
		if len(start) == 0:
			raise DecodeError("o5m input is empty")
		if start[0] != RESET:
			raise DecodeError("o5m input does not start with a reset byte")
		if len(start) < 2 or start[1] != HEADER:
			raise DecodeError("o5m header is missing")
		file_type = self._read_block()
		if file_type not in (b"o5m2", b"o5c2"):
			raise DecodeError("o5m header has an unknown file type")
		self._header_read = True
		self.is_diff = file_type == b"o5c2"
		self.handler.store_is_diff(self.is_diff)

	def _read_block(self):
		"""Reads a dataset's length and contents."""
		try:
			length = read_varint(self.source)
		except (EOFError, ValueError) as err:
			raise DecodeError("o5m dataset length is unreadable: {}".format(err)) from err
		if length > self.max_object_bytes:
			raise DecodeError("o5m dataset is larger than the maximum allowed size")
		data = self.source.read(length)
		if len(data) != length:
			raise DecodeError("o5m input is cut short")
		return data

	def _decode_bounds(self, data):
		#South-western corner then north-eastern corner
		min_lon, pos = decode_zigzag(data, 0)
		min_lat, pos = decode_zigzag(data, pos)
		max_lon, pos = decode_zigzag(data, pos)
		max_lat, pos = decode_zigzag(data, pos)
		return Bounds(min_lon / 1e7, min_lat / 1e7, max_lon / 1e7, max_lat / 1e7)

	def _decode_attributes(self, data):
		if not data.startswith(ATTRIBUTES_MARKER):
			return {} #Some other program's use of this dataset type
		parts = data[len(ATTRIBUTES_MARKER):].split(b"\x00")
		if parts[-1] != b"" or len(parts) % 2 != 1:
			raise ValueError("o5m attributes dataset is cut short")
		parts = [part.decode("utf-8") for part in parts[:-1]]
		return dict(zip(parts[0::2], parts[1::2]))

	def _string(self, data, pos):
		"""The string at pos, up to its zero byte, and the position after it."""
		end = data.find(b"\x00", pos)
		if end < 0:
			raise ValueError("o5m string is not terminated")
		return data[pos:end], end + 1

	def _remember(self, entry):
		#The oldest entry makes way once the table is full
		self._strings[self._strings_next] = entry
		self._strings_next = (self._strings_next + 1) % REF_TABLE_SIZE
		if self._strings_count < REF_TABLE_SIZE:
			self._strings_count += 1

	def _look_up(self, ref, kind):
		if ref > self._strings_count:
			raise ValueError("o5m string reference is out of range")
		entry = self._strings[(self._strings_next - ref) % REF_TABLE_SIZE]
		if not isinstance(entry, kind):
			raise ValueError("o5m string reference is to the wrong kind of string")
		return entry

	def _string_pair(self, data, pos):
		"""The two strings of a pair, inline or a reference to an earlier one,
		and the position after it."""
		ref, pos = decode_varint(data, pos)
		if ref != 0:
			first, second = self._look_up(ref, tuple)
			return first, second, pos
		first, pos = self._string(data, pos)
		second, pos = self._string(data, pos)
		if len(first) + len(second) <= REF_TABLE_LENGTH_THRESHOLD:
			self._remember((first, second))
		return first, second, pos

	def _object_start(self, data):
		"""The ID and metadata that start every object, and the position after them."""
		delta, pos = decode_zigzag(data, 0)
		self._last_id += delta
		meta = MetaData()

		#A dataset may be cut short at any point from here on: the format lets a
		#writer leave out the author, the version, and everything after them
		if pos < len(data):
			version, pos = decode_varint(data, pos)
			meta.version = version or None
			if version != 0 and pos < len(data):
				delta, pos = decode_zigzag(data, pos)
				self._last_timestamp += delta
				if self._last_timestamp != 0:
					meta.timestamp = utc_datetime(self._last_timestamp)
					if pos < len(data):
						delta, pos = decode_zigzag(data, pos)
						self._last_changeset += delta
						meta.changeset = self._last_changeset
						uid, username, pos = self._string_pair(data, pos)
						if uid:
							meta.uid = decode_varint(uid)[0]
						if username:
							meta.username = username.decode("utf-8")
		return self._last_id, meta, pos

	def _tags(self, data, pos):
		tags = {}
		while pos < len(data):
			key, value, pos = self._string_pair(data, pos)
			tags[key.decode("utf-8")] = value.decode("utf-8")
		return tags

	def _reference_section(self, data, pos):
		length, pos = decode_varint(data, pos)
		end = pos + length
		if end > len(data):
			raise ValueError("o5m reference section is longer than its object")
		return data[:end], pos, end

	def _decode_node(self, data):
		obj_id, meta, pos = self._object_start(data)
		if pos >= len(data):
			#Cut down to its ID and metadata: this is how the format says "delete
			#this object". The delta state is left alone.
			meta.visible = False
			return Node(obj_id, meta=meta)

		#Node positions are delta coded in 32 bits, wrapping round, as other o5m
		#programs write them: a step across the antimeridian from +179 to -179
		#degrees is stored as a small positive delta
		delta_lon, pos = decode_zigzag(data, pos)
		delta_lat, pos = decode_zigzag(data, pos)
		self._last_lon = wrap32(self._last_lon + delta_lon)
		self._last_lat = wrap32(self._last_lat + delta_lat)
		return Node(obj_id, self._last_lat / 1e7, self._last_lon / 1e7, self._tags(data, pos), meta)

	def _decode_way(self, data):
		obj_id, meta, pos = self._object_start(data)
		if pos >= len(data):
			meta.visible = False
			return Way(obj_id, meta=meta)

		section, pos, end = self._reference_section(data, pos)
		refs = []
		last = self._last_ref["node"]
		while pos < end:
			delta, pos = decode_zigzag(section, pos)
			last += delta
			refs.append(last)
		self._last_ref["node"] = last
		return Way(obj_id, refs, self._tags(data, end), meta)

	def _decode_relation(self, data):
		obj_id, meta, pos = self._object_start(data)
		if pos >= len(data):
			meta.visible = False
			return Relation(obj_id, meta=meta)

		section, pos, end = self._reference_section(data, pos)
		members = []
		while pos < end:
			delta, pos = decode_zigzag(section, pos)
			ref, pos = decode_varint(section, pos) #Into the string table
			if ref == 0:
				type_and_role, pos = self._string(section, pos)
				if len(type_and_role) <= REF_TABLE_LENGTH_THRESHOLD:
					self._remember(type_and_role)
			else:
				type_and_role = self._look_up(ref, bytes)

			if len(type_and_role) < 1:
				raise ValueError("o5m relation member has no type")
			code = type_and_role[0:1]
			if code == b"0":
				member_type = "node"
			elif code == b"1":
				member_type = "way"
			elif code == b"2":
				member_type = "relation"
			else:
				raise ValueError("o5m relation member has an invalid type")
			self._last_ref[member_type] += delta
			members.append(Member(member_type, self._last_ref[member_type], type_and_role[1:].decode("utf-8")))
		return Relation(obj_id, members, self._tags(data, end), meta)

# ****** encoding ******

class O5mEncoder(Handler):
	"""Encodes the stream it is sent as o5m to a binary file object, or as o5c
	if store_is_diff(True) comes first. finish() writes the end marker; the
	file object is left open.

	o5m has no standard place for attributes of the document as a whole.
	Those given as attributes, or sent with store_attributes before any
	object, are written in cppo5m's dataset (see ATTRIBUTES) straight after
	the header. Entries named version or generator, or with an empty value,
	are left out."""

	def __init__(self, target, attributes=None):
		self.target = target
		self.is_diff = False
		self.attributes = dict(attributes or {})
		self._header_written = False
		self._reset_delta_coding()

	def _reset_delta_coding(self):
		self._last_id = 0
		self._last_timestamp = 0
		self._last_changeset = 0
		self._last_lat = 0
		self._last_lon = 0
		self._last_ref = {"node": 0, "way": 0, "relation": 0}
		#The string table, oldest first, and a dict from each entry to the
		#number it was given when added, so a lookup is a hash lookup instead
		#of a search of the whole table
		self._strings = deque()
		self._string_numbers = {}
		self._strings_added = 0

	def _write_block(self, code, data):
		self.target.write(bytes((code,)) + encode_varint(len(data)) + data)

	def _start(self):
		if self._header_written:
			return
		header = b"o5c2" if self.is_diff else b"o5m2"
		self.target.write(bytes((RESET, HEADER)) + encode_varint(len(header)) + header)
		self._header_written = True

		#Like the bounds, the attributes come before any object
		data = bytearray()
		for key, value in self.attributes.items():
			if key in ("version", "generator") or value is None or str(value) == "":
				continue
			if key == "":
				raise ValueError("o5m attribute names cannot be empty")
			data += _encode_string(key) + b"\x00" + _encode_string(str(value)) + b"\x00"
		if data:
			self._write_block(ATTRIBUTES, ATTRIBUTES_MARKER + bytes(data))

	def store_is_diff(self, is_diff):
		if self._header_written:
			raise ValueError("store_is_diff must come before anything else")
		self.is_diff = is_diff

	def store_attributes(self, attributes):
		if self._header_written:
			raise ValueError("store_attributes must come before any object")
		self.attributes.update(attributes)

	def store_bounds(self, bounds):
		self._start()
		#South-western corner then north-eastern corner
		data = b"".join(encode_zigzag(round_coord(value)) for value in
			(bounds.min_lon, bounds.min_lat, bounds.max_lon, bounds.max_lat))
		self._write_block(BOUNDS, data)

	def _string_ref(self, encoded):
		number = self._string_numbers.get(encoded)
		return None if number is None else self._strings_added - number

	def _add_string(self, encoded):
		if len(self._strings) >= REF_TABLE_SIZE:
			del self._string_numbers[self._strings.popleft()]
		self._strings.append(encoded)
		self._string_numbers[encoded] = self._strings_added
		self._strings_added += 1

	def _write_string_pair(self, first, second, out):
		encoded = first + b"\x00" + second + b"\x00"
		use_table = len(first) + len(second) <= REF_TABLE_LENGTH_THRESHOLD
		if use_table:
			ref = self._string_ref(encoded)
			if ref is not None:
				out += encode_varint(ref)
				return
		out += b"\x00"
		out += encoded
		if use_table:
			self._add_string(encoded)

	def _object_start(self, obj, out):
		out += encode_zigzag(obj.id - self._last_id)
		self._last_id = obj.id

		meta = obj.meta
		if not meta.version:
			out += b"\x00"
			return #The format has nowhere to put the rest without a version
		out += encode_varint(meta.version)
		timestamp = epoch_seconds(meta.timestamp)
		out += encode_zigzag(timestamp - self._last_timestamp)
		self._last_timestamp = timestamp
		if timestamp == 0:
			return
		changeset = meta.changeset or 0
		out += encode_zigzag(changeset - self._last_changeset)
		self._last_changeset = changeset
		self._write_string_pair(encode_varint(meta.uid) if meta.uid else b"",
			_encode_string(meta.username) if meta.username else b"", out)

	def _tags(self, tags, out):
		for key, value in tags.items():
			self._write_string_pair(_encode_string(key), _encode_string(value), out)

	def store_node(self, node):
		self._start()
		data = bytearray()
		self._object_start(node, data)
		if node.meta.visible:
			#Node positions are delta coded in 32 bits, as other o5m programs do
			lon = round_coord(node.lon)
			lat = round_coord(node.lat)
			data += encode_zigzag(wrap32(lon - self._last_lon))
			data += encode_zigzag(wrap32(lat - self._last_lat))
			self._last_lon, self._last_lat = lon, lat
			self._tags(node.tags, data)
		self._write_block(NODE, bytes(data))

	def store_way(self, way):
		self._start()
		data = bytearray()
		self._object_start(way, data)
		if way.meta.visible:
			refs = bytearray()
			last = self._last_ref["node"]
			for ref in way.refs:
				refs += encode_zigzag(ref - last)
				last = ref
			self._last_ref["node"] = last
			data += encode_varint(len(refs))
			data += refs
			self._tags(way.tags, data)
		self._write_block(WAY, bytes(data))

	def store_relation(self, relation):
		self._start()
		data = bytearray()
		self._object_start(relation, data)
		if relation.meta.visible:
			members = bytearray()
			for member in relation.members:
				code = _MEMBER_TYPE_CODES.get(member.type)
				if code is None:
					raise ValueError("Relation member has an invalid type: {}".format(member.type))
				members += encode_zigzag(member.ref - self._last_ref[member.type])
				self._last_ref[member.type] = member.ref

				type_and_role = code + _encode_string(member.role or "")
				ref = self._string_ref(type_and_role)
				if ref is not None:
					members += encode_varint(ref)
				else:
					members += b"\x00" + type_and_role + b"\x00"
					if len(type_and_role) <= REF_TABLE_LENGTH_THRESHOLD:
						self._add_string(type_and_role)
			data += encode_varint(len(members))
			data += members
			self._tags(relation.tags, data)
		self._write_block(RELATION, bytes(data))

	def sync(self):
		self._start()
		self.target.write(b"\xee\x07\x00\x00\x00\x00\x00\x00\x00")

	def reset(self):
		self._start()
		self.target.write(bytes((RESET,)))
		self._reset_delta_coding()

	def finish(self):
		self._start()
		self.target.write(bytes((END,)))
