"""Tests for pyo5m. From the project folder:

	python3 -m unittest discover tests

The osmconvert checks are skipped if osmconvert is not installed."""

import datetime, gzip, os, shutil, subprocess, sys, tempfile, unittest
from dataclasses import replace
from io import BytesIO

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

import pyo5m
from pyo5m import (Bounds, DecodeError, Handler, Member, MetaData, Node, O5mDecoder, O5mEncoder, OsmChange,
	OsmChangeBlock, OsmChangeXmlDecoder, OsmChangeXmlEncoder, OsmData, OsmXmlDecoder, OsmXmlEncoder, Relation, Way)
from pyo5m import o5m, osmxml, varint

DATA = os.path.join(HERE, "data")
UTC = datetime.timezone.utc
WHEN = datetime.datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)

def meta(**changes):
	return replace(MetaData(3, WHEN, 77, 9, "bob"), **changes)

def encode_o5m(data):
	out = BytesIO()
	data.stream_to(O5mEncoder(out))
	return out.getvalue()

def decode_o5m(raw):
	data = OsmData()
	O5mDecoder(BytesIO(raw), data).run()
	return data

def encode_xml(data):
	out = BytesIO()
	data.stream_to(OsmXmlEncoder(out))
	return out.getvalue()

def decode_xml(raw):
	data = OsmData()
	OsmXmlDecoder(BytesIO(raw), data).run()
	return data

def block(code, payload):
	return bytes((code,)) + varint.encode_varint(len(payload)) + payload

def z(value):
	return varint.encode_zigzag(value)

O5M_START = b"\xff\xe0\x04o5m2"

class VarintTests(unittest.TestCase):

	def test_known_values(self):
		for raw, value in ((b"\x05", 5), (b"\x7f", 127), (b"\xc3\x02", 323), (b"\x80\x80\x01", 16384)):
			self.assertEqual(varint.encode_varint(value), raw)
			self.assertEqual(varint.decode_varint(b"x" + raw + b"y", 1), (value, 1 + len(raw)))
			self.assertEqual(varint.read_varint(BytesIO(raw)), value)
		for raw, value in ((b"\x08", 4), (b"\x80\x01", 64), (b"\x03", -2), (b"\x05", -3), (b"\x81\x01", -65)):
			self.assertEqual(varint.encode_zigzag(value), raw)
			self.assertEqual(varint.decode_zigzag(raw), (value, len(raw)))

	def test_extremes(self):
		for value in (0, 1, -1, 2**63 - 1, -2**63):
			self.assertEqual(varint.decode_zigzag(varint.encode_zigzag(value))[0], value)
		raw = varint.encode_varint(2**64 - 1)
		self.assertEqual(len(raw), 10)
		self.assertEqual(varint.decode_varint(raw), (2**64 - 1, 10))

	def test_bad_input(self):
		#Longer than any 64 bit number: refused rather than silently wrong
		with self.assertRaises(ValueError):
			varint.read_varint(BytesIO(b"\xff" * 10 + b"\x01"))
		with self.assertRaises(ValueError):
			varint.decode_zigzag(b"\xff" * 11)
		with self.assertRaises(EOFError):
			varint.read_varint(BytesIO(b"\x80"))
		with self.assertRaises(EOFError):
			varint.decode_varint(b"\x80")
		with self.assertRaises(EOFError):
			varint.decode_varint(b"\x05", 1)
		for value in (-1, 2**64):
			with self.assertRaises(OverflowError):
				varint.encode_varint(value)
		with self.assertRaises(OverflowError):
			varint.encode_zigzag(2**63)

	def test_read_errors_reach_the_caller(self):
		class Failing:
			def read(self, n):
				raise IOError("disk on fire")
		with self.assertRaisesRegex(IOError, "disk on fire"):
			varint.read_varint(Failing())

class O5mTests(unittest.TestCase):

	def test_sample_file_round_trip(self):
		original = pyo5m.load(os.path.join(DATA, "o5mtest.o5m"))
		self.assertEqual((len(original.nodes), len(original.ways), len(original.relations)), (24, 4, 1))
		self.assertEqual(decode_o5m(encode_o5m(original)), original)
		self.assertEqual(pyo5m.load(os.path.join(DATA, "o5mtest.o5m.gz")), original)

	def test_diff_header(self):
		self.assertTrue(encode_o5m(OsmData(is_diff=True)).startswith(b"\xff\xe0\x04o5c2"))
		self.assertTrue(decode_o5m(encode_o5m(OsmData(is_diff=True))).is_diff)
		self.assertFalse(decode_o5m(encode_o5m(OsmData())).is_diff)

	def test_header_and_ordering(self):
		#Without store_is_diff the file is o5m, and even an empty file is valid
		out = BytesIO()
		O5mEncoder(out).finish()
		self.assertEqual(out.getvalue(), O5M_START + b"\xfe")
		out = BytesIO()
		encoder = O5mEncoder(out)
		encoder.store_node(Node(1, 1.5, 2.5, meta=meta()))
		encoder.finish()
		self.assertEqual(decode_o5m(out.getvalue()).nodes, [Node(1, 1.5, 2.5, meta=meta())])
		#Too late to change the header
		for call in (lambda: encoder.store_is_diff(True), lambda: encoder.store_attributes({"a": "b"})):
			with self.assertRaises(ValueError):
				call()

	def test_antimeridian(self):
		#Node positions are delta coded in 32 bits: from +179.9 to -179.9 degrees
		#is a small step east that wraps round
		nodes = [Node(1, 10.0, 179.9, meta=meta()), Node(2, -10.0, -179.9, meta=meta()), Node(3, 0.0, 179.9, meta=meta())]
		raw = encode_o5m(OsmData(nodes=nodes))
		self.assertEqual(decode_o5m(raw).nodes, nodes)
		step = o5m.wrap32(-1799000000 - 1799000000)
		self.assertEqual(step, 696967296)
		self.assertIn(z(step), raw)
		self.assertNotIn(z(-3598000000), raw)

		#A file written with 64 bit deltas reads correctly too
		def node(delta_id, lon):
			return block(0x10, z(delta_id) + b"\x00" + z(lon) + z(0))
		raw = O5M_START + node(1, 1799000000) + node(1, -3598000000) + b"\xfe"
		self.assertEqual([n.lon for n in decode_o5m(raw).nodes], [179.9, -179.9])

	def test_coordinates(self):
		for lat, lon in ((0, 214.8), (95, float("inf")), (float("nan"), 0)):
			with self.assertRaises(ValueError):
				encode_o5m(OsmData(nodes=[Node(1, lat, lon)]))
		#Rounded to the nearest 100 nanodegrees, half away from zero
		self.assertEqual(o5m.round_coord(0.00000005), 1)
		self.assertEqual(o5m.round_coord(-0.00000005), -1)
		self.assertEqual(o5m.round_coord(-179.99999994), -1799999999)

	def test_metadata_variants(self):
		cases = [
			(MetaData(), MetaData()),
			(MetaData(version=2), MetaData(version=2)),
			(MetaData(version=2, timestamp=WHEN), MetaData(version=2, timestamp=WHEN, changeset=0)),
			(MetaData(version=2, timestamp=WHEN, changeset=5), MetaData(version=2, timestamp=WHEN, changeset=5)),
			(MetaData(version=2, timestamp=WHEN, changeset=5, uid=0, username=""),
				MetaData(version=2, timestamp=WHEN, changeset=5)),
			(MetaData(version=2, timestamp=WHEN, changeset=5, uid=12), MetaData(version=2, timestamp=WHEN, changeset=5, uid=12)),
			(meta(username="Zoë"), meta(username="Zoë")),
			#Naive datetimes are taken to be UTC, and aware ones converted
			(meta(timestamp=datetime.datetime(2020, 1, 2, 3, 4, 5)), meta()),
			(meta(timestamp=datetime.datetime(2020, 1, 2, 4, 4, 5, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))), meta()),
			#Extras have nowhere to go in o5m
			(meta(extras={"action": "modify"}), meta()),
		]
		data = OsmData(nodes=[Node(i + 1, 1, 1, meta=given) for i, (given, _) in enumerate(cases)])
		self.assertEqual([n.meta for n in decode_o5m(encode_o5m(data)).nodes], [expected for _, expected in cases])

	def test_ways_and_relations(self):
		ways = [Way(10, [1, 2, 3, 1], {"highway": "path"}, meta()), Way(11, meta=meta()), Way(5, [3], {"a": "b"}, meta())]
		relations = [
			Relation(20, [Member("node", 1, "stop"), Member("way", 10), Member("relation", 21, "sub"), Member("way", 10),
				Member("node", -4, "stop")], {"type": "route"}, meta()),
			Relation(21, meta=meta()),
		]
		data = decode_o5m(encode_o5m(OsmData(ways=ways, relations=relations)))
		self.assertEqual((data.ways, data.relations), (ways, relations))
		with self.assertRaisesRegex(ValueError, "invalid type"):
			encode_o5m(OsmData(relations=[Relation(1, [Member("area", 1)])]))

	def test_deletes(self):
		gone = meta(visible=False)
		data = OsmData(nodes=[Node(1, 5, 5, {"ignored": "yes"}, gone), Node(2, 1, 2, {"kept": "yes"}, meta())],
			ways=[Way(3, [1, 2], meta=gone)], relations=[Relation(4, [Member("node", 1)], meta=gone)], is_diff=True)
		again = decode_o5m(encode_o5m(data))
		self.assertEqual(again.nodes, [Node(1, meta=gone), Node(2, 1, 2, {"kept": "yes"}, meta())])
		self.assertEqual(again.ways, [Way(3, meta=gone)])
		self.assertEqual(again.relations, [Relation(4, meta=gone)])

		#An object cut short after its ID, as an o5c file says delete
		raw = b"\xff\xe0\x04o5c2" + block(0x10, z(7)) + block(0x11, z(1) + b"\x00") + b"\xfe"
		again = decode_o5m(raw)
		self.assertEqual(again.nodes, [Node(7, meta=MetaData(visible=False))])
		self.assertEqual(again.ways, [Way(8, meta=MetaData(visible=False))])

	def test_zero_bytes_are_refused(self):
		for data in (OsmData(nodes=[Node(1, tags={"a\x00b": "c"})]),
				OsmData(nodes=[Node(1, tags={"a": "b\x00"})]),
				OsmData(nodes=[Node(1, meta=meta(username="x\x00y"))]),
				OsmData(relations=[Relation(1, [Member("node", 1, "r\x00")])]),
				OsmData(attributes={"k": "v\x00"})):
			with self.assertRaisesRegex(ValueError, "zero byte"):
				encode_o5m(data)

	def test_string_table(self):
		#A repeated tag is written once and referred to afterwards
		nodes = [Node(i, tags={"amenity": "bench"}, meta=meta()) for i in range(1, 101)]
		raw = encode_o5m(OsmData(nodes=nodes))
		self.assertEqual(raw.count(b"amenity\x00bench\x00"), 1)
		self.assertEqual(decode_o5m(raw).nodes, nodes)

		#More strings than the table holds: old entries make way, and a string
		#that has left the table is written out again
		nodes = [Node(i, tags={"k": str(i % 16000)}, meta=meta()) for i in range(1, 40001)]
		raw = encode_o5m(OsmData(nodes=nodes))
		self.assertEqual(decode_o5m(raw).nodes, nodes)
		self.assertEqual(raw.count(b"k\x005\x00"), 3)

		#Long strings are never put in the table
		nodes = [Node(i, tags={"note": "x" * 300}) for i in range(1, 4)]
		raw = encode_o5m(OsmData(nodes=nodes))
		self.assertEqual(raw.count(b"x" * 300), 3)
		self.assertEqual(decode_o5m(raw).nodes, nodes)

	def test_reset_between_types(self):
		data = OsmData(nodes=[Node(5, 1, 1, {"a": "b"}, meta())], ways=[Way(6, [5], {"a": "b"}, meta())],
			relations=[Relation(7, [Member("way", 6)], {"a": "b"}, meta())])
		raw = encode_o5m(data)
		self.assertEqual(raw.count(b"\xff"), 3) #The start and one between each type
		self.assertEqual(decode_o5m(raw), data)

	def test_attributes(self):
		attributes = {"edit_activity_id": "120", "atomic_edit_id": "45", "boundary": "POLYGON((0 0,1 0,1 1,0 0))"}
		raw = encode_o5m(OsmData(nodes=[Node(1)], attributes=dict(attributes, generator="x", empty="")))
		#cppo5m's dataset, straight after the header
		payload = b"cppo5m-attributes\x00" + b"".join(k.encode() + b"\x00" + v.encode() + b"\x00" for k, v in attributes.items())
		self.assertTrue(raw.startswith(O5M_START + block(0xc0, payload)))
		self.assertEqual(decode_o5m(raw).attributes, attributes)
		#Another program's use of the dataset type is skipped
		self.assertEqual(decode_o5m(O5M_START + block(0xc0, b"something else\x00a\x00") + b"\xfe").attributes, {})

	def test_unknown_datasets_are_skipped(self):
		raw = (O5M_START + block(0xc5, b"\x10\x11\x12") + b"\xee\x07\x00\x00\x00\x00\x00\x00\x00" +
			block(0xe0, b"o5m2") + b"\xf3" + block(0x10, z(1) + b"\x00" + z(10) + z(20)) + b"\xfe")
		self.assertEqual(decode_o5m(raw).nodes, [Node(1, 2e-6, 1e-6)])

	def test_missing_end_marker(self):
		raw = encode_o5m(OsmData(nodes=[Node(1)]))
		self.assertEqual(len(decode_o5m(raw[:-1]).nodes), 1)

	def test_bad_input(self):
		cases = [
			(b"", "empty"),
			(b"\x10", "reset byte"),
			(b"\xff\x10", "header is missing"),
			(b"\xff\xe0\x04o5x2", "unknown file type"),
			(O5M_START + b"\x10\x05\x02", "cut short"),
			(O5M_START + block(0x10, z(1) + b"\x01" + z(1) + z(1) + b"\x05"), "out of range"),
			(O5M_START + block(0x10, z(1) + b"\x00" + z(1) + z(1) + b"\x00ab"), "not terminated"),
			(O5M_START + block(0x11, z(1) + b"\x00" + b"\x09\x02"), "longer than its object"),
			(O5M_START + block(0x12, z(1) + b"\x00" + b"\x04\x02\x00\x00\x00"), "no type"),
			(O5M_START + block(0x12, z(1) + b"\x00" + b"\x04\x02\x007\x00"), "invalid type"),
			(O5M_START + block(0x12, z(1) + b"\x00" + b"\x05\x02\x000a\x00" + b"\x01" + z(0) + b"\x01"), "wrong kind"),
			(O5M_START + block(0x10, z(1) + b"\x00" + z(1) + z(1) + b"\x00\xff\x00a\x00"), "o5m decode failed"),
		]
		for raw, message in cases:
			with self.subTest(raw=raw):
				with self.assertRaisesRegex(DecodeError, message):
					decode_o5m(raw)

	def test_handler_errors_are_not_wrapped(self):
		class Failing(Handler):
			def store_node(self, node):
				raise ValueError("from the handler")
		with self.assertRaisesRegex(ValueError, "^from the handler$") as caught:
			O5mDecoder(BytesIO(encode_o5m(OsmData(nodes=[Node(1)]))), Failing()).run()
		self.assertNotIsInstance(caught.exception, DecodeError)

	def test_step_by_step(self):
		class Recorder(Handler):
			def __init__(self):
				self.calls = []
			def __getattribute__(self, name):
				if name.startswith("store_") or name in ("reset", "finish"):
					return lambda *args: object.__getattribute__(self, "calls").append(name)
				return object.__getattribute__(self, name)
		data = OsmData(nodes=[Node(1)], ways=[Way(2)], bounds=[Bounds(0, 0, 1, 1)], attributes={"a": "b"})
		recorder = Recorder()
		decoder = O5mDecoder(BytesIO(encode_o5m(data)), recorder)
		steps = 0
		while decoder.decode_next():
			steps += 1
		self.assertFalse(decoder.decode_next())
		self.assertEqual(recorder.calls, ["store_is_diff", "store_attributes", "store_bounds", "store_node", "reset",
			"store_way", "reset", "finish"])

@unittest.skipUnless(shutil.which("osmconvert"), "osmconvert is not installed")
class OsmconvertTests(unittest.TestCase):
	"""Files pyo5m writes are read correctly by another o5m implementation, and the
	other way round."""

	def convert(self, raw, source, target):
		with tempfile.TemporaryDirectory() as folder:
			path = os.path.join(folder, "in." + source)
			with open(path, "wb") as fi:
				fi.write(raw)
			return subprocess.run(["osmconvert", path, "--out-" + target], check=True, capture_output=True).stdout

	def test_sample_file(self):
		path = os.path.join(DATA, "o5mtest.o5m")
		theirs = decode_xml(subprocess.run(["osmconvert", path, "--out-osm"], check=True, capture_output=True).stdout)
		self.assertEqual(pyo5m.load(path), theirs)

	def test_both_ways(self):
		data = OsmData(
			nodes=[Node(1, 10.0, 179.9, {"name": "east"}, meta()), Node(2, -10.0, -179.9, {"name": "west"}, meta()),
				Node(3, 0.0, 179.9, {"name": "east"}, meta())],
			ways=[Way(10, [1, 2, 3], {"highway": "path"}, meta())],
			relations=[Relation(20, [Member("node", 1, "stop"), Member("way", 10)], {"type": "route"}, meta())])
		self.assertEqual(decode_xml(self.convert(encode_o5m(data), "o5m", "osm")), data)
		self.assertEqual(decode_o5m(self.convert(encode_xml(data), "osm", "o5m")), data)

class XmlTests(unittest.TestCase):

	def test_round_trip(self):
		data = OsmData(
			nodes=[Node(1, 0.5, -0.25, {"note": "line one\nline\ttwo\r", "quote": "\"it's\" <&>"}, meta()),
				Node(2, 1e-7, -1e-9, meta=meta()), Node(5, meta=meta(visible=False))],
			ways=[Way(3, [1, 2], meta=meta(extras={"action": "modify"}))],
			relations=[Relation(4, [Member("node", 1), Member("way", 3, "outer")], meta=meta(username="Zoë"))],
			bounds=[Bounds(-0.5, -1, 0.5, 1)], attributes={"edit_activity_id": "5"})
		raw = encode_xml(data)
		self.assertNotIn(b"e-0", raw) #No scientific notation
		self.assertIn(b'<node id="2" lat="0.0000001" lon="-0.000000001"', raw)
		self.assertEqual(decode_xml(raw), data)

	def test_sample_files(self):
		data = pyo5m.load(os.path.join(DATA, "o5mrel.osm"))
		self.assertEqual(len(data.relations), 1)
		self.assertEqual(len(data.bounds), 2)
		self.assertEqual(decode_xml(encode_xml(data)), data)
		self.assertEqual(pyo5m.load(os.path.join(DATA, "o5mtest.osm.gz")), pyo5m.load(os.path.join(DATA, "o5mtest.osm")))

	def test_timestamps(self):
		self.assertEqual(osmxml.format_timestamp(WHEN), "2020-01-02T03:04:05Z")
		for text in ("2020-01-02T03:04:05Z", "2020-01-02T04:04:05+01:00", "2020-01-02T03:04:05"):
			self.assertEqual(osmxml.parse_timestamp(text), WHEN)

	def test_lenient_input(self):
		data = decode_xml(b"<osm version='0.6' generator='x' edit_activity_id='3'><relation id='1'>"
			b"<member type='node' ref='2'/><tag k='a'/></relation><node id='4'/><note>hello</note></osm>")
		self.assertEqual(data.relations, [Relation(1, [Member("node", 2)], {"a": ""})])
		self.assertEqual(data.nodes, [Node(4)])
		self.assertEqual(data.attributes, {"edit_activity_id": "3"})

	def test_bad_input(self):
		for raw, message in ((b"<osm><node id='1'", "not well formed"),
				(b"<osmChange/>", "Expected an osm root"),
				(b"<osm><node id='x'/></osm>", "Invalid node"),
				(b"<osm><way id='1'><nd/></way></osm>", "Invalid nd"),
				(b"<osm><relation id='1'><member type='area' ref='1'/></relation></osm>", "invalid type"),
				(b"<osm><node id='1' timestamp='yesterday'/></osm>", "Invalid node")):
			with self.subTest(raw=raw):
				with self.assertRaisesRegex(DecodeError, message):
					decode_xml(raw)

	def test_handler_errors_are_not_wrapped(self):
		class Failing(Handler):
			def store_node(self, node):
				raise KeyError("from the handler")
		with self.assertRaises(KeyError):
			OsmXmlDecoder(BytesIO(b"<osm><node id='1'/></osm>"), Failing()).run()

class OsmChangeTests(unittest.TestCase):

	def test_round_trip(self):
		change = OsmChange(blocks=[
			OsmChangeBlock("create", OsmData(nodes=[Node(-1, 1, 2, {"a": "b"}, MetaData(version=0, changeset=5))], is_diff=True)),
			OsmChangeBlock("modify", OsmData(ways=[Way(3, [1, 2], meta=meta())], is_diff=True)),
			OsmChangeBlock("delete", OsmData(nodes=[Node(1, meta=meta())], relations=[Relation(5, meta=meta())], is_diff=True),
				if_unused=True),
		], attributes={"edit_activity_id": "7"})
		out = BytesIO()
		change.stream_to(OsmChangeXmlEncoder(out))
		raw = out.getvalue()
		#Deletes go relations first
		self.assertLess(raw.index(b"<relation id=\"5\""), raw.index(b"<node id=\"1\""))
		self.assertIn(b"<delete if-unused=\"true\">", raw)
		again = OsmChange()
		OsmChangeXmlDecoder(BytesIO(raw), again).run()
		self.assertEqual(again, change)
		self.assertEqual([n.id for n in again.objects("delete").nodes], [1])

	def test_osm_files_are_refused(self):
		with self.assertRaisesRegex(DecodeError, "Expected an osmChange root"):
			OsmChangeXmlDecoder(BytesIO(b"<osm/>"), OsmChange()).run()

class FileTests(unittest.TestCase):

	def setUp(self):
		self.folder = tempfile.mkdtemp()

	def tearDown(self):
		shutil.rmtree(self.folder)

	def test_formats_follow_the_name(self):
		data = pyo5m.load(os.path.join(DATA, "o5mtest.o5m"))
		for name in ("a.o5m", "a.o5m.gz", "A.OSM", "a.osm.gz", "a.o5c"):
			with self.subTest(name=name):
				path = os.path.join(self.folder, name)
				pyo5m.save(data, path)
				again = pyo5m.load(path)
				self.assertEqual(again.is_diff, name.endswith(".o5c"))
				self.assertEqual(again.relations, data.relations)
				self.assertEqual([n.id for n in again.nodes], [n.id for n in data.nodes])
		with gzip.open(os.path.join(self.folder, "a.o5m.gz"), "rb") as fi:
			self.assertEqual(fi.read(6), O5M_START[:6])
		self.assertFalse(data.is_diff) #save made its own copy for .o5c
		self.assertEqual(oct(os.stat(os.path.join(self.folder, "a.o5m")).st_mode & 0o777),
			oct(0o666 & ~self.umask()))

		change = OsmChange(blocks=[OsmChangeBlock("create", OsmData(nodes=[Node(1)]))])
		path = os.path.join(self.folder, "a.osc.gz")
		pyo5m.save_change(change, path)
		self.assertEqual(pyo5m.load_change(path).blocks[0].data.nodes, [Node(1)])

		for call in (lambda: pyo5m.load("a.pbf"), lambda: pyo5m.save(data, "a"), lambda: pyo5m.load("a.osc"),
				lambda: pyo5m.save_change(change, "a.osm")):
			with self.assertRaises(ValueError):
				call()

	def umask(self):
		value = os.umask(0)
		os.umask(value)
		return value

	def test_failed_save_leaves_the_old_file(self):
		path = os.path.join(self.folder, "a.o5m")
		pyo5m.save(OsmData(nodes=[Node(1)]), path)
		with self.assertRaises(ValueError):
			pyo5m.save(OsmData(nodes=[Node(2), Node(3, 0, 500)]), path)
		self.assertEqual(pyo5m.load(path).nodes, [Node(1)])
		self.assertEqual(os.listdir(self.folder), ["a.o5m"])

	def test_streaming_conversion(self):
		source = os.path.join(DATA, "o5mtest.o5m")
		target = os.path.join(self.folder, "out.osm")
		with open(source, "rb") as fi, open(target, "wb") as fo:
			O5mDecoder(fi, OsmXmlEncoder(fo)).run()
		self.assertEqual(pyo5m.load(target), pyo5m.load(source))

class ModelTests(unittest.TestCase):

	def test_index(self):
		data = OsmData(nodes=[Node(1)], ways=[Way(2, [1])], relations=[Relation(3, [Member("way", 2)])])
		index = data.index()
		self.assertEqual(index["node"][1], data.nodes[0])
		self.assertEqual(index["way"][2], data.ways[0])
		self.assertEqual(index["relation"][3], data.relations[0])

	def test_crop(self):
		data = OsmData(
			nodes=[Node(1, 0.5, 0.5), Node(2, 5, 5), Node(3, 6, 6), Node(4, 0.5, 0.5, meta=MetaData(visible=False))],
			ways=[Way(10, [1, 2, 99]), Way(11, [2, 3])],
			relations=[Relation(20, [Member("way", 10)]), Relation(21, [Member("relation", 20)]),
				Relation(22, [Member("relation", 21)]), Relation(23, [Member("node", 3)])])
		cropped = data.crop((0, 0, 1, 1))
		#Node 99 is not in the data, so the way keeps its reference but no node
		self.assertEqual([n.id for n in cropped.nodes], [1, 2])
		self.assertEqual([w.id for w in cropped.ways], [10])
		self.assertEqual([r.id for r in cropped.relations], [20, 21, 22])
		self.assertEqual(cropped.bounds, [Bounds(0, 0, 1, 1)])

if __name__ == "__main__":
	unittest.main()
