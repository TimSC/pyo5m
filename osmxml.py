import struct, datetime, six, calendar, datetime
import xml.sax.saxutils as sax

# ****** encode osm xml ******

class OsmXmlEncode(object):
	def __init__(self, handle):
		self.outFi = handle

	def StoreIsDiff(self, isDiff):
		self.outFi.write("<?xml version='1.0' encoding='UTF-8'?>\n")
		self.outFi.write("<osm version='0.6' upload='false' generator='pyo5m'>\n")

	def StoreBounds(self, bbox):
		self.outFi.write("  <bounds minlat='{0}' minlon='{1}' maxlat='{2}' maxlon='{3}' />\n".format(bbox[1], bbox[0], bbox[3], bbox[2]))

	def EncodeMetaData(self, metaData, outStream):
		version, timestamp, changeset, uid, username = metaData
		if timestamp is not None:
			outStream.write(" timestamp='{0}'".format(timestamp.isoformat()))
		if version is not None:
			outStream.write(" version='{0}'".format(int(version)))
		if uid is not None:
			outStream.write(" uid='{0}'".format(int(uid)))
		if username is not None:
			outStream.write(" user={0}".format(sax.quoteattr(username)))
		if changeset is not None:
			outStream.write(" changeset='{0}'".format(int(changeset)))

	def StoreNode(self, objectId, metaData, tags, pos):
		self.outFi.write("  <node id='{0}' lat='{1}' lon='{2}'".format(int(objectId), float(pos[0]), float(pos[1])))
		self.EncodeMetaData(metaData, self.outFi)
		if len(tags) > 0:
			self.outFi.write(">\n")
			for k in tags:
				self.outFi.write("    <tag k={0} v={1} />\n".format(sax.quoteattr(k), sax.quoteattr(tags[k])))
			self.outFi.write("  </node>\n")
		else:
			self.outFi.write(" />\n")

	def StoreWay(self, objectId, metaData, tags, refs):
		self.outFi.write("  <way id='{0}'".format(int(objectId)))
		self.EncodeMetaData(metaData, self.outFi)
		self.outFi.write(">\n")
		for ref in refs:
			self.outFi.write("    <nd ref='{0}' />\n".format(int(ref)))
		for k in tags:
			self.outFi.write("    <tag k={0} v={1} />\n".format(sax.quoteattr(k), sax.quoteattr(tags[k])))
		self.outFi.write("  </way>\n")

	def StoreRelation(self, objectId, metaData, tags, refs):
		self.outFi.write("  <relation id='{0}'".format(int(objectId)))
		self.EncodeMetaData(metaData, self.outFi)
		self.outFi.write(">\n")
		for typeStr, refId, role in refs:
			self.outFi.write("    <member type={0} ref='{1}' role={2} />\n".format(sax.quoteattr(typeStr), int(refId), sax.quoteattr(role)))
		for k in tags:
			self.outFi.write("    <tag k={0} v={1} />\n".format(sax.quoteattr(k), sax.quoteattr(tags[k])))
		self.outFi.write("  </relation>\n")

	def Finish(self):
		self.outFi.write("</osm>\n")

if __name__=="__main__":
	TestDecodeNumber()
	TestEncodeNumber()

