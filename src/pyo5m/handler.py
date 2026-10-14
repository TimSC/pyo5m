"""The interfaces that connect decoders to whatever receives their output."""

class DecodeError(ValueError):
	"""The input is not valid in the format being read."""

class Handler(object):
	"""Receives a stream of map objects. Decoders call it, encoders implement it,
	and OsmData both implements it and can replay itself into one, so a decoder
	can feed an encoder directly:

		O5mDecoder(source, OsmXmlEncoder(target)).run()

	Every method does nothing by default, so a handler overrides only what it
	needs. A handler that cannot continue raises; the exception reaches
	whoever is driving the stream unchanged."""

	def store_is_diff(self, is_diff):
		"""Whether the stream is a diff (o5c) rather than a snapshot. Sent before
		anything else."""

	def store_attributes(self, attributes):
		"""Attributes of the document as a whole that are not part of the map,
		such as the edit IDs a dump was taken at, as a dict of strings. Sent
		before any object, and only if the document has some. The version and
		generator are never included."""

	def store_bounds(self, bounds):
		pass

	def store_node(self, node):
		pass

	def store_way(self, way):
		pass

	def store_relation(self, relation):
		pass

	def reset(self):
		"""Marks a boundary in the stream, normally a change of object type. The
		o5m encoder restarts its delta coding here; most handlers ignore it."""

	def finish(self):
		"""The stream is complete. Sent exactly once, after the last object."""

class ChangeHandler(object):
	"""Receives the action blocks of an osmChange document in order."""

	def store_attributes(self, attributes):
		"""Attributes of the osmChange element, other than version and
		generator. Sent before any block, and only if there are some."""

	def store_change_block(self, block):
		pass

	def finish(self):
		pass
