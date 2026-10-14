"""OSM XML, and osmChange XML."""

import datetime
import decimal
import math
import xml.parsers.expat as expat

from .handler import ChangeHandler, DecodeError, Handler
from .model import (CHANGE_ACTIONS, MEMBER_TYPES, Bounds, Member, MetaData, Node, OsmChangeBlock, OsmData,
	Relation, Way, utc_datetime)

READ_BLOCK_SIZE = 1024 * 1024

def parse_timestamp(text):
	"""An aware UTC datetime from an ISO 8601 timestamp such as
	2020-01-02T03:04:05Z. One with an offset is converted to UTC, and one
	with neither is taken to be UTC already."""
	text = text.strip()
	if text[-1:] in ("Z", "z"):
		text = text[:-1] + "+00:00"
	return utc_datetime(datetime.datetime.fromisoformat(text))

def format_timestamp(value):
	"""The OSM form of a timestamp, 2020-01-02T03:04:05Z."""
	return utc_datetime(value).strftime("%Y-%m-%dT%H:%M:%SZ")

def format_coord(value):
	"""A coordinate with the fewest digits that read back as exactly the same
	number, and without scientific notation."""
	value = float(value)
	if not math.isfinite(value):
		raise ValueError("Coordinate is not a number: {}".format(value))
	text = format(decimal.Decimal(repr(value)), "f")
	if "." in text:
		text = text.rstrip("0").rstrip(".")
	return "0" if text == "-0" else text

_escapes = {"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;",
	#A parser turns these into spaces in an attribute unless they are references
	"\n": "&#10;", "\r": "&#13;", "\t": "&#9;"}
_escape_table = str.maketrans(_escapes)

def escape(value):
	return str(value).translate(_escape_table)

# ****** decoding ******

_META_ATTRIBUTES = ("id", "version", "timestamp", "changeset", "uid", "user", "visible", "lat", "lon")

def _parse_meta(attrs):
	meta = MetaData()
	if "version" in attrs:
		meta.version = int(attrs["version"])
	if "timestamp" in attrs:
		meta.timestamp = parse_timestamp(attrs["timestamp"])
	if "changeset" in attrs:
		meta.changeset = int(attrs["changeset"])
	if "uid" in attrs:
		meta.uid = int(attrs["uid"])
	meta.username = attrs.get("user")
	meta.visible = attrs.get("visible", "true").lower() != "false"
	meta.extras = {k: v for k, v in attrs.items() if k not in _META_ATTRIBUTES}
	return meta

class _XmlParser(object):
	"""Reads OSM objects from either kind of document. Subclasses say what to do
	with the root, the objects and (for osmChange) the action elements.
	Everything found is queued while expat runs, and handed over afterwards,
	so exceptions raised by handlers are not mistaken for decode errors."""

	root_name = None

	def __init__(self, source):
		self.source = source
		self._parser = expat.ParserCreate()
		self._parser.StartElementHandler = self._start_element
		self._parser.EndElementHandler = self._end_element
		self._depth = 0
		self._object = None
		self._pending = []
		self._finished = False

	def run(self):
		while self.decode_next():
			pass

	def decode_next(self):
		"""Decodes the next block of input. Returns False once it is all done."""
		if self._finished:
			return False
		data = self.source.read(READ_BLOCK_SIZE)
		try:
			if len(data) > 0:
				self._parser.Parse(data, False)
			else:
				self._parser.Parse(b"", True)
		except expat.ExpatError as err:
			raise DecodeError("XML is not well formed: {}".format(err)) from err
		for call, item in self._pending:
			call(item)
		self._pending = []
		if len(data) == 0:
			self._finished = True
			self._finish()
			return False
		return True

	def _queue(self, call, item):
		self._pending.append((call, item))

	def _start_element(self, name, attrs):
		self._depth += 1
		try:
			if self._depth == 1:
				if name != self.root_name:
					raise DecodeError("Expected an {} root element but found {}".format(self.root_name, name))
				self._root(attrs)
			elif self._object is not None:
				self._child(name, attrs)
			elif name in ("node", "way", "relation") and self._object_depth_ok():
				obj_id = int(attrs["id"])
				meta = _parse_meta(attrs)
				if name == "node":
					self._object = Node(obj_id, float(attrs.get("lat", 0.0)), float(attrs.get("lon", 0.0)), meta=meta)
				elif name == "way":
					self._object = Way(obj_id, meta=meta)
				else:
					self._object = Relation(obj_id, meta=meta)
			else:
				self._other(name, attrs)
		except (KeyError, ValueError) as err:
			if isinstance(err, DecodeError):
				raise
			raise DecodeError("Invalid {} element: {}".format(name, err)) from err

	def _child(self, name, attrs):
		if name == "tag":
			self._object.tags[attrs["k"]] = attrs.get("v", "")
		elif name == "nd" and isinstance(self._object, Way):
			self._object.refs.append(int(attrs["ref"]))
		elif name == "member" and isinstance(self._object, Relation):
			if attrs["type"] not in MEMBER_TYPES:
				raise DecodeError("Relation member has an invalid type: {}".format(attrs["type"]))
			self._object.members.append(Member(attrs["type"], int(attrs["ref"]), attrs.get("role", "")))

	def _end_element(self, name):
		if self._object is not None and name in ("node", "way", "relation") and self._depth == self._object_depth():
			self._store(self._object)
			self._object = None
		else:
			self._end_other(name)
		self._depth -= 1

	def _object_depth_ok(self):
		return self._depth == self._object_depth()

class OsmXmlDecoder(_XmlParser):
	"""Decodes an OSM XML document from a file object, sending what it finds to
	a Handler. run() decodes everything; decode_next() decodes a block of
	input at a time and returns False once it is done. The handler's finish
	is called at the end either way."""

	root_name = "osm"

	def __init__(self, source, handler):
		_XmlParser.__init__(self, source)
		self.handler = handler

	def _object_depth(self):
		return 2

	def _root(self, attrs):
		self._queue(self.handler.store_is_diff, False)
		attributes = {k: v for k, v in attrs.items() if k not in ("version", "generator")}
		if attributes:
			self._queue(self.handler.store_attributes, attributes)

	def _other(self, name, attrs):
		if name == "bounds" and self._depth == 2:
			self._queue(self.handler.store_bounds, Bounds(float(attrs["minlon"]), float(attrs["minlat"]),
				float(attrs["maxlon"]), float(attrs["maxlat"])))

	def _store(self, obj):
		if isinstance(obj, Node):
			self._queue(self.handler.store_node, obj)
		elif isinstance(obj, Way):
			self._queue(self.handler.store_way, obj)
		else:
			self._queue(self.handler.store_relation, obj)

	def _end_other(self, name):
		pass

	def _finish(self):
		self.handler.finish()

class OsmChangeXmlDecoder(_XmlParser):
	"""Decodes an osmChange document from a file object, sending each action
	element to a ChangeHandler as an OsmChangeBlock. Used as OsmXmlDecoder is."""

	root_name = "osmChange"

	def __init__(self, source, handler):
		_XmlParser.__init__(self, source)
		self.handler = handler
		self._block = None

	def _object_depth(self):
		return 3

	def _object_depth_ok(self):
		return self._depth == 3 and self._block is not None

	def _root(self, attrs):
		attributes = {k: v for k, v in attrs.items() if k not in ("version", "generator")}
		if attributes:
			self._queue(self.handler.store_attributes, attributes)

	def _other(self, name, attrs):
		if self._depth == 2 and name in CHANGE_ACTIONS:
			self._block = OsmChangeBlock(name, OsmData(is_diff=True),
				attrs.get("if-unused", "false").lower() not in ("false", "0", ""))

	def _store(self, obj):
		if isinstance(obj, Node):
			self._block.data.nodes.append(obj)
		elif isinstance(obj, Way):
			self._block.data.ways.append(obj)
		else:
			self._block.data.relations.append(obj)

	def _end_other(self, name):
		if self._depth == 2 and self._block is not None and name == self._block.action:
			self._queue(self.handler.store_change_block, self._block)
			self._block = None

	def _finish(self):
		self.handler.finish()

# ****** encoding ******

class _XmlWriter(object):

	def __init__(self, target, attributes, root_name):
		self.target = target
		self.attributes = dict(attributes or {})
		self._root_name = root_name
		self._header_written = False
		self._finished = False

	def _write(self, text):
		self.target.write(text.encode("utf-8"))

	def _start(self):
		if self._header_written:
			return
		self._header_written = True
		out = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<", self._root_name, " version=\"0.6\" generator=\"pyo5m\""]
		for key, value in self.attributes.items():
			if key in ("version", "generator") or value is None or str(value) == "":
				continue
			out.append(" {}=\"{}\"".format(key, escape(value)))
		out.append(">\n")
		self._write("".join(out))

	def _check_attributes_allowed(self):
		if self._header_written:
			raise ValueError("store_attributes must come before anything else")

	def _object(self, obj, indent):
		meta = obj.meta
		kind = "node" if isinstance(obj, Node) else "way" if isinstance(obj, Way) else "relation"
		out = [indent, "<", kind, " id=\"", str(int(obj.id)), "\""]
		if kind == "node" and meta.visible:
			out.append(" lat=\"{}\" lon=\"{}\"".format(format_coord(obj.lat), format_coord(obj.lon)))
		if meta.version is not None:
			out.append(" version=\"{}\"".format(int(meta.version)))
		if meta.timestamp is not None:
			out.append(" timestamp=\"{}\"".format(format_timestamp(meta.timestamp)))
		if meta.changeset is not None:
			out.append(" changeset=\"{}\"".format(int(meta.changeset)))
		if meta.uid is not None:
			out.append(" uid=\"{}\"".format(int(meta.uid)))
		if meta.username is not None:
			out.append(" user=\"{}\"".format(escape(meta.username)))
		if not meta.visible:
			out.append(" visible=\"false\"")
		for key, value in meta.extras.items():
			out.append(" {}=\"{}\"".format(key, escape(value)))

		children = []
		if kind == "way":
			children.extend("{}  <nd ref=\"{}\"/>\n".format(indent, int(ref)) for ref in obj.refs)
		elif kind == "relation":
			for member in obj.members:
				if member.type not in MEMBER_TYPES:
					raise ValueError("Relation member has an invalid type: {}".format(member.type))
				children.append("{}  <member type=\"{}\" ref=\"{}\" role=\"{}\"/>\n".format(
					indent, member.type, int(member.ref), escape(member.role or "")))
		children.extend("{}  <tag k=\"{}\" v=\"{}\"/>\n".format(indent, escape(k), escape(v)) for k, v in obj.tags.items())
		if children:
			out.append(">\n")
			out.extend(children)
			out.append("{}</{}>\n".format(indent, kind))
		else:
			out.append("/>\n")
		self._write("".join(out))

	def _end(self):
		if self._finished:
			return
		self._start()
		self._write("</{}>\n".format(self._root_name))
		self._finished = True

class OsmXmlEncoder(_XmlWriter, Handler):
	"""Writes the stream it is sent as OSM XML to a binary file object.
	attributes, or those sent with store_attributes before anything else,
	become attributes of the osm element; entries named version or
	generator, or with an empty value, are left out. finish() closes the
	document; the file object is left open."""

	def __init__(self, target, attributes=None):
		_XmlWriter.__init__(self, target, attributes, "osm")

	def store_attributes(self, attributes):
		self._check_attributes_allowed()
		self.attributes.update(attributes)

	def store_bounds(self, bounds):
		self._start()
		self._write("  <bounds minlat=\"{}\" minlon=\"{}\" maxlat=\"{}\" maxlon=\"{}\"/>\n".format(
			format_coord(bounds.min_lat), format_coord(bounds.min_lon),
			format_coord(bounds.max_lat), format_coord(bounds.max_lon)))

	def store_node(self, node):
		self._start()
		self._object(node, "  ")

	def store_way(self, way):
		self._start()
		self._object(way, "  ")

	def store_relation(self, relation):
		self._start()
		self._object(relation, "  ")

	def finish(self):
		self._end()

class OsmChangeXmlEncoder(_XmlWriter, ChangeHandler):
	"""Writes the change blocks it is sent as an osmChange document to a binary
	file object. Within a block, nodes come first, then ways, then relations,
	except in a delete, where the order is reversed so nothing is deleted
	while still in use."""

	def __init__(self, target, attributes=None):
		_XmlWriter.__init__(self, target, attributes, "osmChange")

	def store_attributes(self, attributes):
		self._check_attributes_allowed()
		self.attributes.update(attributes)

	def store_change_block(self, block):
		if block.action not in CHANGE_ACTIONS:
			raise ValueError("Unknown osmChange action: {}".format(block.action))
		self._start()
		if_unused = " if-unused=\"true\"" if block.if_unused and block.action == "delete" else ""
		self._write("  <{}{}>\n".format(block.action, if_unused))
		groups = [block.data.nodes, block.data.ways, block.data.relations]
		if block.action == "delete":
			groups.reverse()
		for group in groups:
			for obj in group:
				self._object(obj, "    ")
		self._write("  </{}>\n".format(block.action))

	def finish(self):
		self._end()
