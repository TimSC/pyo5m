import o5m, osmxml

# ****** generic osm data store ******

class OsmData(object):
	def __init__(self):
		self.nodes=[]
		self.ways=[]
		self.relations=[]
		self.bounds=[]
		self.isDiff = False
	
	def LoadFromO5m(self, fi):
		dec = o5m.O5mDecode(fi)
		dec.funcStoreNode = self.StoreNode
		dec.funcStoreWay = self.StoreWay
		dec.funcStoreRelation = self.StoreRelation
		dec.funcStoreBounds = self.StoreBounds
		dec.funcStoreIsDiff = self.StoreIsDiff
		dec.DecodeHeader()

		eof = False
		while not eof:
			eof = dec.DecodeNext()

	def SaveToO5m(self, fi):
		enc = o5m.O5mEncode(fi)
		enc.StoreIsDiff(self.isDiff)
		for bbox in self.bounds:
			enc.StoreBounds(bbox)
		for nodeData in self.nodes:
			enc.StoreNode(*nodeData)
		enc.Reset()
		for wayData in self.ways:
			enc.StoreWay(*wayData)
		enc.Reset()
		for relationData in self.relations:
			enc.StoreRelation(*relationData)
		enc.Finish()

	def LoadFromOsmXml(self, fi):
		dec = osmxml.OsmXmlDecode(fi)
		dec.funcStoreNode = self.StoreNode
		dec.funcStoreWay = self.StoreWay
		dec.funcStoreRelation = self.StoreRelation
		dec.funcStoreBounds = self.StoreBounds
		dec.funcStoreIsDiff = self.StoreIsDiff

		eof = False
		while not eof:
			eof = dec.DecodeNext()
	
	def SaveToOsmXml(self, fi):
		enc = osmxml.OsmXmlEncode(fi)
		enc.StoreIsDiff(self.isDiff)
		for bbox in self.bounds:
			enc.StoreBounds(bbox)
		for nodeData in self.nodes:
			enc.StoreNode(*nodeData)
		for wayData in self.ways:
			enc.StoreWay(*wayData)
		for relationData in self.relations:
			enc.StoreRelation(*relationData)
		enc.Finish()

	def StoreNode(self, objectId, metaData, tags, pos):
		self.nodes.append([objectId, metaData, tags, pos])

	def StoreWay(self, objectId, metaData, tags, refs):
		self.ways.append([objectId, metaData, tags, refs])

	def StoreRelation(self, objectId, metaData, tags, refs):
		self.relations.append([objectId, metaData, tags, refs])

	def StoreBounds(self, bbox):
		self.bounds.append(bbox)

	def StoreIsDiff(self, isDiff):
		self.isDiff = isDiff

	
