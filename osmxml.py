import struct, datetime, six, calendar, datetime
import xml.sax.saxutils as sax
import xml.parsers.expat as expat

def ValOrNone(dictIn, key):
	if key in dictIn:
		return dictIn[key]
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
			out[k] = v
		return out

	def start_element(self, name, attrs):
		self.depth += 1
		if name in ["node", "way", "relation"]:
			self.attrs = self.AttrTypes(attrs)
		if name == "tag":
			self.tags[attrs['k']] = attrs['v']
		if name == "nd":
			self.members.append(int(attrs['ref']))
		if name == "member":
			self.members.append((attrs['type'], int(attrs['ref']), attrs['role']))
		if name == "bounds":
			if self.parent.funcStoreBounds is not None:
				bbox = float(attrs['minlon']), float(attrs['minlat']), float(attrs['maxlon']), float(attrs['maxlat'])
				self.parent.funcStoreBounds(bbox)

	def end_element(self, name):
		if name == "node":
			if self.parent.funcStoreNode is not None:
				metaData = (ValOrNone(self.attrs,"version"), ValOrNone(self.attrs,"timestamp"), 
					ValOrNone(self.attrs,"changeset"), ValOrNone(self.attrs,"uid"), 
					ValOrNone(self.attrs,"username"))
				self.parent.funcStoreNode(self.attrs["id"], metaData, self.tags, [self.attrs["lat"],self.attrs["lon"]])
			self.attrs = {}
			self.tags = {}
			self.members = []

		if name == "way":
			if self.parent.funcStoreWay is not None:
				metaData = (ValOrNone(self.attrs,"version"), ValOrNone(self.attrs,"timestamp"), 
					ValOrNone(self.attrs,"changeset"), ValOrNone(self.attrs,"uid"), 
					ValOrNone(self.attrs,"username"))
				self.parent.funcStoreWay(self.attrs["id"], metaData, self.tags, self.members)
			self.attrs = {}
			self.tags = {}
			self.members = []

		if name == "relation":
			if self.parent.funcStoreRelation is not None:
				metaData = (ValOrNone(self.attrs,"version"), ValOrNone(self.attrs,"timestamp"), 
					ValOrNone(self.attrs,"changeset"), ValOrNone(self.attrs,"uid"), 
					ValOrNone(self.attrs,"username"))
				self.parent.funcStoreRelation(self.attrs["id"], metaData, self.tags, self.members)
			self.attrs = {}
			self.tags = {}
			self.members = []

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
		self.outFi = handle

	def StoreIsDiff(self, isDiff):
		self.outFi.write("<?xml version='1.0' encoding='UTF-8'?>\n".encode("utf-8"))
		self.outFi.write("<osm version='0.6' upload='false' generator='pyo5m'>\n".encode("utf-8"))

	def StoreBounds(self, bbox):
		self.outFi.write("  <bounds minlat='{0}' minlon='{1}' maxlat='{2}' maxlon='{3}' />\n".format(bbox[1], bbox[0], bbox[3], bbox[2]).encode("utf-8"))

	def EncodeMetaData(self, metaData, outStream):
		version, timestamp, changeset, uid, username = metaData
		if timestamp is not None:
			outStream.write(" timestamp='{0}'".format(timestamp.isoformat()).encode("utf-8"))
		if version is not None:
			outStream.write(" version='{0}'".format(int(version)).encode("utf-8"))
		if uid is not None:
			outStream.write(" uid='{0}'".format(int(uid)).encode("utf-8"))
		if username is not None:
			outStream.write(" user={0}".format(sax.quoteattr(username)).encode("utf-8"))
		if changeset is not None:
			outStream.write(" changeset='{0}'".format(int(changeset)).encode("utf-8"))

	def StoreNode(self, objectId, metaData, tags, pos):
		self.outFi.write("  <node id='{0}' lat='{1}' lon='{2}'".format(int(objectId), float(pos[0]), float(pos[1])).encode("utf-8"))
		self.EncodeMetaData(metaData, self.outFi)
		if len(tags) > 0:
			self.outFi.write(">\n".encode("utf-8"))
			for k in tags:
				self.outFi.write("    <tag k={0} v={1} />\n".format(sax.quoteattr(k), sax.quoteattr(tags[k])).encode("utf-8"))
			self.outFi.write("  </node>\n".encode("utf-8"))
		else:
			self.outFi.write(" />\n".encode("utf-8"))

	def StoreWay(self, objectId, metaData, tags, refs):
		self.outFi.write("  <way id='{0}'".format(int(objectId)).encode("utf-8"))
		self.EncodeMetaData(metaData, self.outFi)
		self.outFi.write(">\n".encode("utf-8"))
		for ref in refs:
			self.outFi.write("    <nd ref='{0}' />\n".format(int(ref)).encode("utf-8"))
		for k in tags:
			self.outFi.write("    <tag k={0} v={1} />\n".format(sax.quoteattr(k), sax.quoteattr(tags[k])).encode("utf-8"))
		self.outFi.write("  </way>\n".encode("utf-8"))

	def StoreRelation(self, objectId, metaData, tags, refs):
		self.outFi.write("  <relation id='{0}'".format(int(objectId)).encode("utf-8"))
		self.EncodeMetaData(metaData, self.outFi)
		self.outFi.write(">\n".encode("utf-8"))
		for typeStr, refId, role in refs:
			self.outFi.write("    <member type={0} ref='{1}' role={2} />\n".format(sax.quoteattr(typeStr), int(refId), sax.quoteattr(role)).encode("utf-8"))
		for k in tags:
			self.outFi.write("    <tag k={0} v={1} />\n".format(sax.quoteattr(k), sax.quoteattr(tags[k])).encode("utf-8"))
		self.outFi.write("  </relation>\n".encode("utf-8"))

	def Finish(self):
		self.outFi.write("</osm>\n".encode("utf-8"))

if __name__=="__main__":
	TestDecodeNumber()
	TestEncodeNumber()

