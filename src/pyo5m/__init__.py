"""Reading and writing OpenStreetMap data as o5m, o5c, OSM XML and osmChange XML.

The quickest way in:

	import pyo5m
	data = pyo5m.load("area.o5m.gz")       #An OsmData
	pyo5m.save(data, "area.osm")
	change = pyo5m.load_change("diff.osc") #An OsmChange

To stream instead of holding everything in memory, connect a decoder to a
Handler, such as an encoder:

	with open("area.o5m", "rb") as source, open("area.osm", "wb") as target:
		pyo5m.O5mDecoder(source, pyo5m.OsmXmlEncoder(target)).run()
"""

import dataclasses
import gzip
import os
import tempfile

from .handler import ChangeHandler, DecodeError, Handler
from .model import (Bounds, Member, MetaData, Node, OsmChange, OsmChangeBlock, OsmData, Relation, Way)
from .o5m import O5mDecoder, O5mEncoder
from .osmxml import OsmChangeXmlDecoder, OsmChangeXmlEncoder, OsmXmlDecoder, OsmXmlEncoder

__version__ = "2.0.0"

# The formats by file name ending, before any .gz
_DECODERS = {"o5m": O5mDecoder, "o5c": O5mDecoder, "osm": OsmXmlDecoder}
_ENCODERS = {"o5m": O5mEncoder, "o5c": O5mEncoder, "osm": OsmXmlEncoder}

def format_of(path):
	"""The format a file name implies, and whether it is gzipped: for example
	("o5m", True) for area.o5m.gz. Raises ValueError for anything else."""
	name = str(path).lower()
	gzipped = name.endswith(".gz")
	if gzipped:
		name = name[:-3]
	extension = name.rsplit(".", 1)[-1] if "." in name else ""
	if extension not in ("o5m", "o5c", "osm", "osc"):
		raise ValueError("Cannot tell the format of {}: it should end in .o5m, .o5c, .osm or .osc, "
			"optionally followed by .gz".format(path))
	return extension, gzipped

def open_file(path, mode="rb"):
	"""Opens a file in binary mode, through gzip if its name ends in .gz."""
	return gzip.open(path, mode) if format_of(path)[1] else open(path, mode)

def _write_file(path, write):
	"""Calls write with a binary file object, gzipping if the name says so. The
	data goes to a temporary file beside the destination, which takes its
	place only once write has finished, so a failure leaves any existing file
	as it was."""
	gzipped = format_of(path)[1]
	folder = os.path.dirname(os.path.abspath(path))
	handle, temporary = tempfile.mkstemp(dir=folder, prefix=".pyo5m-", suffix=".tmp")
	try:
		with os.fdopen(handle, "wb") as raw:
			if gzipped:
				with gzip.GzipFile(fileobj=raw, mode="wb") as target:
					write(target)
			else:
				write(raw)
		#mkstemp makes the file private; give it the permissions open would have
		umask = os.umask(0)
		os.umask(umask)
		os.chmod(temporary, 0o666 & ~umask)
		os.replace(temporary, path)
	except BaseException:
		os.remove(temporary)
		raise

def decoder(source, handler, format):
	"""A decoder for a format ("o5m", "o5c", "osm" or "osc") reading from a
	binary file object. "osc" needs a ChangeHandler; the rest a Handler."""
	if format == "osc":
		return OsmChangeXmlDecoder(source, handler)
	return _DECODERS[format](source, handler)

def encoder(target, format, attributes=None):
	"""An encoder for a format writing to a binary file object; see decoder."""
	if format == "osc":
		return OsmChangeXmlEncoder(target, attributes)
	return _ENCODERS[format](target, attributes)

def load(path):
	"""Reads a whole .o5m, .o5c or .osm file, optionally gzipped, into an OsmData."""
	format, _ = format_of(path)
	if format == "osc":
		raise ValueError("{} is an osmChange file; use load_change".format(path))
	data = OsmData()
	with open_file(path, "rb") as source:
		decoder(source, data, format).run()
	return data

def save(data, path):
	"""Writes an OsmData as .o5m, .o5c or .osm, optionally gzipped. A .o5c file
	is always written as a change file, whatever data.is_diff says. An
	existing file is replaced only once the new one is complete."""
	format, _ = format_of(path)
	if format == "osc":
		raise ValueError("{} is an osmChange file; use save_change".format(path))
	if format == "o5c" and not data.is_diff:
		data = dataclasses.replace(data, is_diff=True) #A shallow copy
	_write_file(path, lambda target: data.stream_to(encoder(target, format)))

def load_change(path):
	"""Reads a whole .osc file, optionally gzipped, into an OsmChange."""
	if format_of(path)[0] != "osc":
		raise ValueError("{} is not an osmChange (.osc) file".format(path))
	change = OsmChange()
	with open_file(path, "rb") as source:
		OsmChangeXmlDecoder(source, change).run()
	return change

def save_change(change, path):
	"""Writes an OsmChange as .osc, optionally gzipped."""
	if format_of(path)[0] != "osc":
		raise ValueError("{} is not an osmChange (.osc) file".format(path))
	_write_file(path, lambda target: change.stream_to(OsmChangeXmlEncoder(target)))
