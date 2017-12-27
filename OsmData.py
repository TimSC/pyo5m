from __future__ import print_function
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

class OsmChange(object):
	def __init__(self):
		self.create = OsmData()
		self.modify = OsmData()
		self.delete = OsmData()
		self.dec = None

	def ChangeStart(self, changeType):
		#print "start", changeType
		if changeType == "create":
			self.dec.funcStoreNode = self.create.StoreNode
			self.dec.funcStoreWay = self.create.StoreWay
			self.dec.funcStoreRelation = self.create.StoreRelation
		if changeType == "modify":
			self.dec.funcStoreNode = self.modify.StoreNode
			self.dec.funcStoreWay = self.modify.StoreWay
			self.dec.funcStoreRelation = self.modify.StoreRelation
		if changeType == "delete":
			self.dec.funcStoreNode = self.delete.StoreNode
			self.dec.funcStoreWay = self.delete.StoreWay
			self.dec.funcStoreRelation = self.delete.StoreRelation

	def ChangeEnd(self, changeType):
		#print "end", changeType
		self.dec.funcStoreNode = None
		self.dec.funcStoreWay = None
		self.dec.funcStoreRelation = None

	def LoadFromOscXml(self, fi):
		self.dec = osmxml.OsmXmlDecode(fi)
		self.dec.funcChangeStart = self.ChangeStart
		self.dec.funcChangeEnd = self.ChangeEnd

		eof = False
		while not eof:
			eof = self.dec.DecodeNext()

		self.dec = None

#Utilitiy functions

def Crop(osmData, bbox):

	#Get nodes in bbox
	nodesInBbox = set()
	nodeDict = {}
	for node in osmData.nodes:
		objId, metaData, tags, [lat, lon] = node
		nodeDict[objId] = (objId, metaData, tags, [lat, lon])
		if lon < bbox[0] or lon > bbox[2] or lat < bbox[1] or lat > bbox[3]:
			continue		
		nodesInBbox.add(objId)

	#Get ways in bbox
	waysInQuery = set()
	wayDict = {}
	nodesInQuery = nodesInBbox.copy()
	for way in osmData.ways:
		objId, metaData, tags, members = way
		wayDict[objId] = way
		membersSet = set(members)
		nodesInMembers = len(membersSet.intersection(nodesInBbox))
		if nodesInMembers == 0:
			continue
		nodesInQuery.update(members)
		waysInQuery.add(objId)

	#Get relations in bbox
	relationsInQuery = set()
	relationDict = {}
	for relation in osmData.relations:
		hit = False
		objId, metaData, tags, members = relation
		relationDict[objId] = relation
		
		for memTy, memId, memRole in members:
			hit = (memTy == "node" and memId in nodesInQuery)
			if hit: break
			hit = (memTy == "way" and memId in waysInQuery)
			if hit: break
		if not hit:
			continue
		relationsInQuery.add(objId)

	#Get parent relations
	relationsAndParents = relationsInQuery.copy()
	uncheckedRelations = relationsInQuery.copy()
	for i in range(10):
		if len(uncheckedRelations) == 0:
			break
		foundRelations = set()

		for objId, metaData, tags, members in osmData.relations:
			hit = False
			for memTy, memId, memRole in members:
				hit = (memTy == "relation" and memId in uncheckedRelations)
				if hit: break
			if not hit:
				continue
			if objId not in relationsAndParents:
				foundRelations.add(objId)

		relationsAndParents.update(foundRelations)
		uncheckedRelations = foundRelations

	#Copy results to object
	outOsmData = OsmData()
	for objId in nodesInQuery:
		outOsmData.nodes.append(nodeDict[objId])
	for objId in waysInQuery:
		outOsmData.ways.append(wayDict[objId])
	for objId in relationsAndParents:
		outOsmData.relations.append(relationDict[objId])
	outOsmData.bounds = [bbox]

	return outOsmData

def IndexObjectsById(osmData):
	out = {'nodes': {}, 'ways': {}, 'relations': {}}

	for objId, metaData, tags, pos in osmData.nodes:
		out['nodes'][objId] = metaData, tags, pos
	for objId, metaData, tags, members in osmData.ways:
		out['ways'][objId] = metaData, tags, members
	for objId, metaData, tags, members in osmData.ways:
		out['relations'][objId] = metaData, tags, members
	return out

