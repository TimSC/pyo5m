from __future__ import print_function
import xml.sax.saxutils as sax
import xml.parsers.expat as expat
import codecs, datetime

def ValOrNone(dictIn, key):
	if key in dictIn:
		return dictIn[key]
	return None

def BoolValOrNone(dictIn, key):
	if key in dictIn:
		return dictIn[key].lower() == "true"
	return None

# ****** decode osm xml ******

class DecodeHandler(object):
	def __init__(self, parent):
		self.depth = 0
		self.attrs = {}
		self.tags = {}
		self.members = []
		self.parent = parent

	def AttrTypes(self, attr):
		out = {}
		for k in attr:
			v = attr[k]
			if k == "lat":
				v = float(v)
			elif k == "lon":
				v = float(v)
			elif k == "version":
				v = int(v)
			elif k == "id":
				v = int(v)
			elif k == "changeset":
				v = int(v)
			elif k == "uid":
				v = int(v)
			elif k == "timestamp":
				v = datetime.datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ")
			out[k] = v
		return out

	def start_element(self, name, attrs):
		self.depth += 1
		if name in ["node", "way", "relation"]:
			self.attrs = self.AttrTypes(attrs)
		elif name == "tag":
			self.tags[attrs['k']] = attrs['v']
		elif name == "nd":
			self.members.append(int(attrs['ref']))
		elif name == "member":
			self.members.append((attrs['type'], int(attrs['ref']), attrs['role']))
		elif name == "bounds" and self.parent.funcStoreBounds is not None:
				bbox = (float(attrs['minlon']), float(attrs['minlat']), 
					float(attrs['maxlon']), float(attrs['maxlat']))
				self.parent.funcStoreBounds(bbox)
		elif name in ["create", "modify", "delete"]:
			if self.parent.funcChangeStart is not None:
				self.parent.funcChangeStart(name)

	def DecodeMetaData(self):
		extras = {}
		for k in self.attrs:
			if k in ["id", "version", "timestamp", "changeset", "uid", "user", "lat", "lon"]:
				continue
			extras[k] = self.attrs[k]
		metaData = (ValOrNone(self.attrs,"version"), ValOrNone(self.attrs,"timestamp"), 
					ValOrNone(self.attrs,"changeset"), ValOrNone(self.attrs,"uid"), 
					ValOrNone(self.attrs,"user"), extras)
		return metaData

	def end_element(self, name):
		if name == "node":
			if self.parent.funcStoreNode is not None:
				metaData = self.DecodeMetaData()
				self.parent.funcStoreNode(self.attrs["id"], metaData, 
					self.tags, [self.attrs["lat"],self.attrs["lon"]])
			self.attrs = {}
			self.tags = {}
			self.members = []

		elif name == "way":
			if self.parent.funcStoreWay is not None:
				metaData = self.DecodeMetaData()
				self.parent.funcStoreWay(self.attrs["id"], metaData, self.tags, self.members)
			self.attrs = {}
			self.tags = {}
			self.members = []

		elif name == "relation":
			if self.parent.funcStoreRelation is not None:
				metaData = self.DecodeMetaData()
				self.parent.funcStoreRelation(self.attrs["id"], metaData, self.tags, self.members)
			self.attrs = {}
			self.tags = {}
			self.members = []

		elif name in ["create", "modify", "delete"]:
			if self.parent.funcChangeEnd is not None:
				self.parent.funcChangeEnd(name)

		self.depth -= 1

	def flush(self):
		pass

class OsmXmlDecode(object):
	def __init__(self, fi):
		self.fi = fi
		self.parser = expat.ParserCreate("UTF-8")
		self.decode = DecodeHandler(self)
		self.parser.StartElementHandler = self.decode.start_element
		self.parser.EndElementHandler = self.decode.end_element
		self.readBlockSize = 10*1024*1024
		self.funcStoreNode = None
		self.funcStoreWay = None
		self.funcStoreRelation = None
		self.funcStoreBounds = None
		self.funcStoreIsDiff = None
		self.funcChangeStart = None
		self.funcChangeEnd = None

	def DecodeNext(self):
		xmlData = self.fi.read(self.readBlockSize)
		if len(xmlData) > 0:
			self.parser.Parse(xmlData)
			return False
		self.parser.Parse("", 1) #Finalize parser
		self.decode.flush()
		return True

# ****** encode osm xml ******

class OsmXmlEncode(object):
	def __init__(self, handle):
		self.writer = codecs.getwriter("utf-8")(handle)
		self.writer.write(u"<?xml version='1.0' encoding='UTF-8'?>\n")
		self.writer.write(u"<osm version='0.6' upload='false' generator='pyo5m'>\n")

	def StoreIsDiff(self, isDiff):
		pass

	def StoreBounds(self, bbox):
		self.writer.write(u"  <bounds minlat='{0:.9f}' minlon='{1:.9f}' maxlat='{2:.9f}' maxlon='{3:.9f}' />\n"
			.format(bbox[1], bbox[0], bbox[3], bbox[2]))

	def EncodeMetaData(self, metaData, outStream):
		version, timestamp, changeset, uid, username, extras = metaData
		if timestamp is not None:
			outStream.write(u" timestamp='{0}'".format(timestamp.isoformat()))
		if version is not None:
			outStream.write(u" version='{0}'".format(int(version)))
		if uid is not None:
			outStream.write(u" uid='{0}'".format(int(uid)))
		if username is not None:
			outStream.write(u" user={0}".format(sax.quoteattr(username)))
		if changeset is not None:
			outStream.write(u" changeset='{0}'".format(int(changeset)))
		for k in extras:
			outStream.write(u" {}={}".format(k, sax.quoteattr(extras[k])))

	def StoreNode(self, objectId, metaData, tags, pos):
		self.writer.write(u"  <node id='{0}' lat='{1:.9f}' lon='{2:.9f}'"
			.format(int(objectId), float(pos[0]), float(pos[1])))
		self.EncodeMetaData(metaData, self.writer)
		if len(tags) > 0:
			self.writer.write(u">\n")
			for k in tags:
				self.writer.write(u"    <tag k={0} v={1} />\n"
					.format(sax.quoteattr(k), sax.quoteattr(tags[k])))
			self.writer.write("  </node>\n")
		else:
			self.writer.write(u" />\n")

	def StoreWay(self, objectId, metaData, tags, refs):
		self.writer.write(u"  <way id='{0}'".format(int(objectId)))
		self.EncodeMetaData(metaData, self.writer)
		self.writer.write(u">\n")
		for ref in refs:
			self.writer.write(u"    <nd ref='{0}' />\n".format(int(ref)))
		for k in tags:
			self.writer.write(u"    <tag k={0} v={1} />\n"
				.format(sax.quoteattr(k), sax.quoteattr(tags[k])))
		self.writer.write(u"  </way>\n")

	def StoreRelation(self, objectId, metaData, tags, refs):
		self.writer.write(u"  <relation id='{0}'".format(int(objectId)))
		self.EncodeMetaData(metaData, self.writer)
		self.writer.write(u">\n")
		for typeStr, refId, role in refs:
			self.writer.write(u"    <member type={0} ref='{1}' role={2} />\n".format(
				sax.quoteattr(typeStr), int(refId), sax.quoteattr(role)))
		for k in tags:
			self.writer.write(u"    <tag k={0} v={1} />\n"
				.format(sax.quoteattr(k), sax.quoteattr(tags[k])))
		self.writer.write(u"  </relation>\n")

	def Finish(self):
		self.writer.write(u"</osm>\n")
		self.writer.flush()

	def Reset(self):
		pass  #Relevent to o5m but not xml

