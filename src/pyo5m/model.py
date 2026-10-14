"""Map objects, and in-memory documents that hold them."""

import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .handler import ChangeHandler, Handler

EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

def utc_datetime(value):
	"""An aware UTC datetime from a datetime (a naive one is taken to be UTC
	already) or seconds since the epoch. None stays None."""
	if value is None:
		return None
	if isinstance(value, datetime.datetime):
		if value.tzinfo is None:
			return value.replace(tzinfo=datetime.timezone.utc)
		return value.astimezone(datetime.timezone.utc)
	return EPOCH + datetime.timedelta(seconds=int(value))

def epoch_seconds(value):
	"""Whole seconds since the epoch, from what utc_datetime takes. None is 0."""
	if value is None:
		return 0
	return int((utc_datetime(value) - EPOCH) // datetime.timedelta(seconds=1))

@dataclass
class MetaData:
	"""Who last changed an object, and when. Any of it may be unknown (None).
	visible is False for a deleted object. extras holds any other attributes
	an XML file gives the object, as strings."""
	version: Optional[int] = None
	timestamp: Optional[datetime.datetime] = None #Aware, in UTC
	changeset: Optional[int] = None
	uid: Optional[int] = None
	username: Optional[str] = None
	visible: bool = True
	extras: Dict[str, str] = field(default_factory=dict)

@dataclass
class Node:
	id: int
	lat: float = 0.0
	lon: float = 0.0
	tags: Dict[str, str] = field(default_factory=dict)
	meta: MetaData = field(default_factory=MetaData)

@dataclass
class Way:
	id: int
	refs: List[int] = field(default_factory=list)
	tags: Dict[str, str] = field(default_factory=dict)
	meta: MetaData = field(default_factory=MetaData)

@dataclass(frozen=True)
class Member:
	type: str #"node", "way" or "relation"
	ref: int
	role: str = ""

MEMBER_TYPES = ("node", "way", "relation")

@dataclass
class Relation:
	id: int
	members: List[Member] = field(default_factory=list)
	tags: Dict[str, str] = field(default_factory=dict)
	meta: MetaData = field(default_factory=MetaData)

@dataclass(frozen=True)
class Bounds:
	min_lon: float
	min_lat: float
	max_lon: float
	max_lat: float

	def contains(self, lat, lon):
		return self.min_lat <= lat <= self.max_lat and self.min_lon <= lon <= self.max_lon

@dataclass
class OsmData(Handler):
	"""A whole map document in memory. As a Handler it collects what a decoder
	sends it; stream_to sends it on to another handler, such as an encoder."""
	nodes: List[Node] = field(default_factory=list)
	ways: List[Way] = field(default_factory=list)
	relations: List[Relation] = field(default_factory=list)
	bounds: List[Bounds] = field(default_factory=list)
	attributes: Dict[str, str] = field(default_factory=dict)
	is_diff: bool = False

	def clear(self):
		self.__init__()

	def is_empty(self):
		return not (self.nodes or self.ways or self.relations)

	def store_is_diff(self, is_diff):
		self.is_diff = is_diff

	def store_attributes(self, attributes):
		self.attributes.update(attributes)

	def store_bounds(self, bounds):
		self.bounds.append(bounds)

	def store_node(self, node):
		self.nodes.append(node)

	def store_way(self, way):
		self.ways.append(way)

	def store_relation(self, relation):
		self.relations.append(relation)

	def stream_to(self, handler, finish=True):
		"""Sends the document to a handler: nodes, then ways, then relations,
		with a reset between each type."""
		handler.store_is_diff(self.is_diff)
		if self.attributes:
			handler.store_attributes(dict(self.attributes))
		for bounds in self.bounds:
			handler.store_bounds(bounds)
		for node in self.nodes:
			handler.store_node(node)
		handler.reset()
		for way in self.ways:
			handler.store_way(way)
		handler.reset()
		for relation in self.relations:
			handler.store_relation(relation)
		if finish:
			handler.finish()

	def index(self):
		"""The objects by ID: a dict with "node", "way" and "relation" entries,
		each a dict from ID to object."""
		return {
			"node": {node.id: node for node in self.nodes},
			"way": {way.id: way for way in self.ways},
			"relation": {relation.id: relation for relation in self.relations},
		}

	def crop(self, bounds):
		"""What a map query of an area gives: the nodes inside it, the ways with
		one of those nodes and all their nodes, the relations with one of
		those nodes or ways as a member, and the relations that contain those
		relations, at any depth. bounds is a Bounds or (min lon, min lat, max
		lon, max lat). Returns a new OsmData; the objects are shared."""
		if not isinstance(bounds, Bounds):
			bounds = Bounds(*bounds)
		inside = {node.id for node in self.nodes if node.meta.visible and bounds.contains(node.lat, node.lon)}

		way_ids = set()
		node_ids = set(inside)
		for way in self.ways:
			if not inside.isdisjoint(way.refs):
				way_ids.add(way.id)
				node_ids.update(way.refs)

		relation_ids = set()
		for relation in self.relations:
			for member in relation.members:
				if (member.type == "node" and member.ref in node_ids) or (member.type == "way" and member.ref in way_ids):
					relation_ids.add(relation.id)
					break

		#Parents of the relations found, and their parents in turn
		unchecked = set(relation_ids)
		while unchecked:
			found = set()
			for relation in self.relations:
				if relation.id in relation_ids:
					continue
				if any(member.type == "relation" and member.ref in unchecked for member in relation.members):
					found.add(relation.id)
			relation_ids.update(found)
			unchecked = found

		#A way may refer to nodes the data does not have; they are left out
		return OsmData(
			nodes=[node for node in self.nodes if node.id in node_ids],
			ways=[way for way in self.ways if way.id in way_ids],
			relations=[relation for relation in self.relations if relation.id in relation_ids],
			bounds=[bounds],
			attributes=dict(self.attributes))

CHANGE_ACTIONS = ("create", "modify", "delete")

@dataclass
class OsmChangeBlock:
	"""One action element of an osmChange document."""
	action: str #"create", "modify" or "delete"
	data: OsmData = field(default_factory=OsmData)
	if_unused: bool = False #The if-unused attribute, meaningful for delete

@dataclass
class OsmChange(ChangeHandler):
	"""An osmChange document in memory, as its action blocks in order."""
	blocks: List[OsmChangeBlock] = field(default_factory=list)
	attributes: Dict[str, str] = field(default_factory=dict)

	def store_attributes(self, attributes):
		self.attributes.update(attributes)

	def store_change_block(self, block):
		self.blocks.append(block)

	def stream_to(self, handler, finish=True):
		if self.attributes:
			handler.store_attributes(dict(self.attributes))
		for block in self.blocks:
			handler.store_change_block(block)
		if finish:
			handler.finish()

	def objects(self, action):
		"""Every object in the blocks with this action, as one OsmData."""
		out = OsmData()
		for block in self.blocks:
			if block.action == action:
				out.nodes.extend(block.data.nodes)
				out.ways.extend(block.data.ways)
				out.relations.extend(block.data.relations)
		return out
