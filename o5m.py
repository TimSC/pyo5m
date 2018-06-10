from __future__ import print_function
import struct, datetime, six, calendar, datetime
from . import Encoding
from io import BytesIO

# ****** o5m utilities ******

def TestDecodeNumber():
	assert (Encoding.DecodeVarint(BytesIO(b'\x05')) == 5)
	assert (Encoding.DecodeVarint(BytesIO(b'\x7f')) == 127)
	assert (Encoding.DecodeVarint(BytesIO(b'\xc3\x02')) == 323)
	assert (Encoding.DecodeVarint(BytesIO(b'\x80\x80\x01')) == 16384)
	assert (Encoding.DecodeZigzag(BytesIO(b'\x08')) == 4)
	assert (Encoding.DecodeZigzag(BytesIO(b'\x80\x01')) == 64)
	assert (Encoding.DecodeZigzag(BytesIO(b'\x03')) == -2)
	assert (Encoding.DecodeZigzag(BytesIO(b'\x05')) == -3)
	assert (Encoding.DecodeZigzag(BytesIO(b'\x81\x01')) == -65)

def TestEncodeNumber():
	assert (Encoding.EncodeVarint(5) == b'\x05')
	assert (Encoding.EncodeVarint(127) == b'\x7f')
	assert (Encoding.EncodeVarint(323) == b'\xc3\x02')
	assert (Encoding.EncodeVarint(16384) == b'\x80\x80\x01')
	assert (Encoding.EncodeZigzag(4) == b'\x08')
	assert (Encoding.EncodeZigzag(64) == b'\x80\x01')
	assert (Encoding.EncodeZigzag(-2) == b'\x03')
	assert (Encoding.EncodeZigzag(-3) == b'\x05')
	assert (Encoding.EncodeZigzag(-65) == b'\x81\x01')

# ****** o5m decoder ******

class O5mDecode(object):
	def __init__(self, handle):
		self.handle = handle
		if struct.unpack("B", self.handle.read(1))[0] != 0xFF:
			raise RuntimeError("First byte has wrong value")
		if struct.unpack("B", self.handle.read(1))[0] != 0xE0:
			raise RuntimeError("Missing header")
		
		self.ResetDeltaCoding()
		self.funcStoreNode = None
		self.funcStoreWay = None
		self.funcStoreRelation = None
		self.funcStoreBounds = None
		self.funcStoreIsDiff = None
		self.refTableLengthThreshold = 250
		self.refTableMaxSize = 15000
		self.headerDecoded = False

	def ResetDeltaCoding(self):
		self.lastObjId = 0 #Used in delta encoding
		self.lastTimeStamp = 0
		self.lastChangeSet = 0
		self.stringPairs = []
		self.lastLat = 0
		self.lastLon = 0
		self.lastRefNode = 0
		self.lastRefWay = 0
		self.lastRefRelation = 0
	
	def DecodeNext(self):
		if not self.headerDecoded:
			raise RuntimeError("Header decode needs to be done first")

		code = struct.unpack("B", self.handle.read(1))[0]
		#print "found", hex(code)
		if code == 0x10:
			self.DecodeNode()
			return False
		if code == 0x11:
			self.DecodeWay()
			return False
		if code == 0x12:
			self.DecodeRelation()
			return False
		if code == 0xdb:
			self.DecodeBoundingBox()
			return False
		if code == 0xff:
			#Used in delta encoding information
			self.ResetDeltaCoding()
			return False #Reset code
		if code == 0xfe:
			return True #End of file
		if code >= 0xF0 and code <= 0xFF:
			return False
	
		#Default behavior to skip unknown data
		length = Encoding.DecodeVarint(self.handle)
		unknownDataSet = self.handle.read(length)
		return False

	def DecodeHeader(self):
		length = Encoding.DecodeVarint(self.handle)
		fileType = self.handle.read(length)
		if self.funcStoreIsDiff != None:
			self.funcStoreIsDiff("o5c2"==fileType)
		self.headerDecoded = True
	
	def DecodeBoundingBox(self):
		length = Encoding.DecodeVarint(self.handle)
		
		#south-western corner 
		x1 = Encoding.DecodeZigzag(self.handle) / 1e7 #lon
		y1 = Encoding.DecodeZigzag(self.handle) / 1e7 #lat

		#north-eastern corner
		x2 = Encoding.DecodeZigzag(self.handle) / 1e7 #lon
		y2 = Encoding.DecodeZigzag(self.handle) / 1e7 #lat

		if self.funcStoreBounds != None:
			self.funcStoreBounds([x1, y1, x2, y2])

	def DecodeSingleString(self, stream):
		outStr = BytesIO()
		code = 0x01
		while code != 0x00:
			rawVal = stream.read(1)
			code = struct.unpack("B", rawVal)[0]
			if code != 0x00:
				outStr.write(rawVal)
		return outStr.getvalue()

	def ConsiderAddToStringRefTable(self, firstStr, secondStr):
		#Consider adding pair to string reference table
		if len(firstStr) + len(secondStr) <= self.refTableLengthThreshold:
			combinedRaw = firstStr+b"\x00"+secondStr+b"\x00"
			self.AddBuffToStringRefTable(combinedRaw)

	def AddBuffToStringRefTable(self, buff):
		self.stringPairs.append(buff)

		#Make sure it does not grow forever
		if len(self.stringPairs) > self.refTableMaxSize:
			self.stringPairs = self.stringPairs[-self.refTableMaxSize:]

	def ReadStringPair(self, stream):
		ref = Encoding.DecodeVarint(stream)
		if ref == 0x00:
			#print "new pair"
			firstStr = self.DecodeSingleString(stream)
			secondStr = self.DecodeSingleString(stream)
			self.ConsiderAddToStringRefTable(firstStr, secondStr)
		else:
			#print "ref", ref
			prevPair = BytesIO(self.stringPairs[-ref])
			firstStr = self.DecodeSingleString(prevPair)
			secondStr = self.DecodeSingleString(prevPair)
		return firstStr, secondStr

	def DecodeMetaData(self, nodeDataStream):
		#Decode author and time stamp
		version = Encoding.DecodeVarint(nodeDataStream)
		timestamp = None
		changeset = None
		uid = None
		username = None
		if version != 0:
			deltaTime = Encoding.DecodeZigzag(nodeDataStream)
			self.lastTimeStamp += deltaTime
			timestamp = datetime.datetime.utcfromtimestamp(self.lastTimeStamp)
			#print "timestamp", self.lastTimeStamp, deltaTime
			if self.lastTimeStamp != 0:
				deltaChangeSet = Encoding.DecodeZigzag(nodeDataStream)
				self.lastChangeSet += deltaChangeSet
				changeset = self.lastChangeSet
				#print "changeset", self.lastChangeSet, deltaChangeSet
				firstString, secondString = self.ReadStringPair(nodeDataStream)

				if len(firstString) > 0:
					uid = Encoding.DecodeVarint(BytesIO(firstString))
					#print "uid", uid
				if len(secondString) > 0:
					username = secondString.decode("utf-8")

		visible = None
		current = None
		extras = {}
		return version, timestamp, changeset, uid, username, extras

	def DecodeNode(self):
		length = Encoding.DecodeVarint(self.handle)
		nodeData = self.handle.read(length)

		#Decode object ID
		nodeDataStream = BytesIO(nodeData)
		deltaId = Encoding.DecodeZigzag(nodeDataStream)
		self.lastObjId += deltaId
		objectId = self.lastObjId 

		metaData = self.DecodeMetaData(nodeDataStream)

		self.lastLon += Encoding.DecodeZigzag(nodeDataStream)
		self.lastLat += Encoding.DecodeZigzag(nodeDataStream)
		lon = self.lastLon / 1e7
		lat = self.lastLat / 1e7
		#print lat, lon

		tags = {}
		while nodeDataStream.tell() < len(nodeData):
			firstString, secondString = self.ReadStringPair(nodeDataStream)
			#print "strlen", len(firstString), len(secondString)
			#print "str", firstString.decode("utf-8"), secondString.decode("utf-8")
			tags[firstString.decode("utf-8")] = secondString.decode("utf-8")
		#print tags

		if self.funcStoreNode is not None:
			self.funcStoreNode(objectId, metaData, tags, (lat, lon))

	def DecodeWay(self):
		length = Encoding.DecodeVarint(self.handle)
		objData = self.handle.read(length)

		#Decode object ID
		objDataStream = BytesIO(objData)
		deltaId = Encoding.DecodeZigzag(objDataStream)
		self.lastObjId += deltaId
		objectId = self.lastObjId 
		#print "objectId", objectId

		metaData = self.DecodeMetaData(objDataStream)

		refLen = Encoding.DecodeVarint(objDataStream)
		#print "len ref", refLen

		refStart = objDataStream.tell()
		refs = []
		while objDataStream.tell() < refStart + refLen:
			self.lastRefNode += Encoding.DecodeZigzag(objDataStream)
			refs.append(self.lastRefNode)
			#print "ref", self.lastRefNode

		tags = {}
		while objDataStream.tell() < len(objData):
			firstString, secondString = self.ReadStringPair(objDataStream)
			#print "strlen", len(firstString), len(secondString)
			#print "str", firstString.decode("utf-8"), secondString.decode("utf-8")
			tags[firstString.decode("utf-8")] = secondString.decode("utf-8")
		#print tags

		if self.funcStoreWay is not None:
			self.funcStoreWay(objectId, metaData, tags, refs)

	def DecodeRelation(self):
		length = Encoding.DecodeVarint(self.handle)
		objData = self.handle.read(length)

		#Decode object ID
		objDataStream = BytesIO(objData)
		deltaId = Encoding.DecodeZigzag(objDataStream)
		self.lastObjId += deltaId
		objectId = self.lastObjId 
		#print "objectId", objectId

		metaData = self.DecodeMetaData(objDataStream)

		refLen = Encoding.DecodeVarint(objDataStream)
		#print "len ref", refLen

		refStart = objDataStream.tell()
		refs = []

		while objDataStream.tell() < refStart + refLen:
			deltaRef = Encoding.DecodeZigzag(objDataStream)
			refIndex = Encoding.DecodeVarint(objDataStream) #Index into reference table
			if refIndex == 0:
				typeAndRoleRaw = self.DecodeSingleString(objDataStream)
				typeAndRole = typeAndRoleRaw.decode("utf-8")
				if len(typeAndRoleRaw) <= self.refTableLengthThreshold:
					self.AddBuffToStringRefTable(typeAndRoleRaw)
			else:
				typeAndRole = self.stringPairs[-refIndex].decode("utf-8")

			typeCode = int(typeAndRole[0])
			role = typeAndRole[1:]
			refId = None
			if typeCode == 0:
				self.lastRefNode += deltaRef
				refId = self.lastRefNode
			if typeCode == 1:
				self.lastRefWay += deltaRef
				refId = self.lastRefWay
			if typeCode == 2:
				self.lastRefRelation += deltaRef
				refId = self.lastRefRelation
			typeStr = None
			if typeCode == 0:
				typeStr = "node"
			if typeCode == 1:
				typeStr = "way"
			if typeCode == 2:
				typeStr = "relation"
			refs.append((typeStr, refId, role))
			#print "rref", refId, typeCode, role

		tags = {}
		while objDataStream.tell() < len(objData):
			firstString, secondString = self.ReadStringPair(objDataStream)
			#print "strlen", len(firstString), len(secondString)
			#print "str", firstString.decode("utf-8"), secondString.decode("utf-8")
			tags[firstString.decode("utf-8")] = secondString.decode("utf-8")
		#print tags

		if self.funcStoreRelation is not None:
			self.funcStoreRelation(objectId, metaData, tags, refs)

# ****** encode o5m ******

class O5mEncode(object):
	def __init__(self, handle):
		self.handle = handle
		self.handle.write(b"\xff")
		
		self.ResetDeltaCoding()
		self.funcStoreNode = None
		self.funcStoreWay = None
		self.funcStoreRelation = None
		self.funcStoreBounds = None
		self.funcStoreIsDiff = None
		self.refTableLengthThreshold = 250
		self.refTableMaxSize = 15000

	def ResetDeltaCoding(self):
		self.lastObjId = 0 #Used in delta encoding
		self.lastTimeStamp = 0
		self.lastChangeSet = 0
		self.stringPairs = []
		self.lastLat = 0
		self.lastLon = 0
		self.lastRefNode = 0
		self.lastRefWay = 0
		self.lastRefRelation = 0

	def StoreIsDiff(self, isDiff):
		self.handle.write(b"\xe0")
		if isDiff:
			headerData = "o5c2".encode("utf-8")
		else:
			headerData = "o5m2".encode("utf-8")
		self.handle.write(Encoding.EncodeVarint(len(headerData)))
		self.handle.write(headerData)

	def StoreBounds(self, bbox):

		#south-western corner 
		bboxData = []
		bboxData.append(Encoding.EncodeZigzag(round(bbox[0] * 1e7))) #lon
		bboxData.append(Encoding.EncodeZigzag(round(bbox[1] * 1e7))) #lat

		#north-eastern corner
		bboxData.append(Encoding.EncodeZigzag(round(bbox[2] * 1e7))) #lon
		bboxData.append(Encoding.EncodeZigzag(round(bbox[3] * 1e7))) #lat
		
		combinedData = b''.join(bboxData)
		self.handle.write(b'\xdb')
		self.handle.write(Encoding.EncodeVarint(len(combinedData)))
		self.handle.write(combinedData)

	def EncodeMetaData(self, version, timestamp, changeset, uid, username, outStream):
		#Decode author and time stamp
		if version != 0 and version != None:
			outStream.write(Encoding.EncodeVarint(version))
			if timestamp != None:
				timestamp = calendar.timegm(timestamp.utctimetuple())
			else:
				timestamp = 0
			deltaTime = timestamp - self.lastTimeStamp
			outStream.write(Encoding.EncodeZigzag(deltaTime))
			self.lastTimeStamp = timestamp
			#print "timestamp", self.lastTimeStamp, deltaTime
			if timestamp != 0:
				#print changeset
				deltaChangeSet = changeset - self.lastChangeSet
				outStream.write(Encoding.EncodeZigzag(deltaChangeSet))
				self.lastChangeSet = changeset
				encUid = b""
				if uid is not None:
					encUid = Encoding.EncodeVarint(uid)
				encUsername = b""
				if username is not None:
					encUsername = username.encode("utf-8")
				self.WriteStringPair(encUid, encUsername, outStream)
		else:
			outStream.write(Encoding.EncodeVarint(0))

	def EncodeSingleString(self, strIn):
		return strIn + b'\x00'

	def WriteStringPair(self, firstString, secondString, tmpStream):
		encodedStrings = firstString + b"\x00" + secondString + b"\x00"
		if len(firstString) + len(secondString) <= self.refTableLengthThreshold:
			try:
				existIndex = self.stringPairs.index(encodedStrings)
				tmpStream.write(Encoding.EncodeVarint(len(self.stringPairs) - existIndex))
				return
			except ValueError:
				pass #Key value pair not currently in reference table

		tmpStream.write(b"\x00")
		tmpStream.write(encodedStrings)
		if len(firstString) + len(secondString) <= self.refTableLengthThreshold:
			self.AddToRefTable(encodedStrings)

	def AddToRefTable(self, encodedStrings):
		self.stringPairs.append(encodedStrings)

		#Limit size of reference table
		if len(self.stringPairs) > self.refTableMaxSize:
			self.stringPairs = self.stringPairs[-self.refTableMaxSize:]

	def StoreNode(self, objectId, metaData, tags, pos):
		self.handle.write(b"\x10")

		#Object ID
		tmpStream = BytesIO()
		deltaId = objectId - self.lastObjId
		tmpStream.write(Encoding.EncodeZigzag(deltaId))
		self.lastObjId = objectId

		version, timestamp, changeset, uid, username, extras = metaData
		self.EncodeMetaData(version, timestamp, changeset, uid, username, tmpStream)

		#Position
		lon = round(pos[1] * 1e7)
		deltaLon = lon - self.lastLon
		tmpStream.write(Encoding.EncodeZigzag(deltaLon))
		self.lastLon = lon
		lat = round(pos[0] * 1e7)
		deltaLat = lat - self.lastLat
		tmpStream.write(Encoding.EncodeZigzag(deltaLat))
		self.lastLat = lat

		for key in tags:
			val = tags[key]
			self.WriteStringPair(key.encode("utf-8"), val.encode("utf-8"), tmpStream)

		binData = tmpStream.getvalue()
		self.handle.write(Encoding.EncodeVarint(len(binData)))
		self.handle.write(binData)

	def StoreWay(self, objectId, metaData, tags, refs):
		self.handle.write(b"\x11")

		#Object ID
		tmpStream = BytesIO()
		deltaId = objectId - self.lastObjId
		tmpStream.write(Encoding.EncodeZigzag(deltaId))
		self.lastObjId = objectId

		#Store meta data
		version, timestamp, changeset, uid, username, extras = metaData
		self.EncodeMetaData(version, timestamp, changeset, uid, username, tmpStream)

		#Store nodes
		refStream = BytesIO()
		for ref in refs:
			deltaRef = ref - self.lastRefNode
			refStream.write(Encoding.EncodeZigzag(deltaRef))
			self.lastRefNode = ref

		encRefs = refStream.getvalue()
		tmpStream.write(Encoding.EncodeVarint(len(encRefs)))
		tmpStream.write(encRefs)

		#Write tags
		for key in tags:
			val = tags[key]
			self.WriteStringPair(key.encode("utf-8"), val.encode("utf-8"), tmpStream)

		binData = tmpStream.getvalue()
		self.handle.write(Encoding.EncodeVarint(len(binData)))
		self.handle.write(binData)
		
	def StoreRelation(self, objectId, metaData, tags, refs):
		self.handle.write(b"\x12")

		#Object ID
		tmpStream = BytesIO()
		deltaId = objectId - self.lastObjId
		tmpStream.write(Encoding.EncodeZigzag(deltaId))
		self.lastObjId = objectId

		#Store meta data
		version, timestamp, changeset, uid, username, extras = metaData
		self.EncodeMetaData(version, timestamp, changeset, uid, username, tmpStream)

		#Store referenced children
		refStream = BytesIO()
		for typeStr, refId, role in refs:
			typeCode = None
			deltaRef = None
			if typeStr == "node":
				typeCode = 0
				deltaRef = refId - self.lastRefNode
				self.lastRefNode = refId
			if typeStr == "way":
				typeCode = 1
				deltaRef = refId - self.lastRefWay
				self.lastRefWay = refId
			if typeStr == "relation":
				typeCode = 2
				deltaRef = refId - self.lastRefRelation
				self.lastRefRelation = refId

			refStream.write(Encoding.EncodeZigzag(deltaRef))

			typeCodeAndRole = (str(typeCode) + role).encode("utf-8")
			try:
				refIndex = self.stringPairs.index(typeCodeAndRole)
				refStream.write(Encoding.EncodeVarint(len(self.stringPairs) - refIndex))
			except ValueError:
				refStream.write(b'\x00') #String start byte
				refStream.write(self.EncodeSingleString(typeCodeAndRole))
				if len(typeCodeAndRole) <= self.refTableLengthThreshold:
					self.AddToRefTable(typeCodeAndRole)

		encRefs = refStream.getvalue()
		tmpStream.write(Encoding.EncodeVarint(len(encRefs)))
		tmpStream.write(encRefs)

		#Write tags
		for key in tags:
			val = tags[key]
			self.WriteStringPair(key.encode("utf-8"), val.encode("utf-8"), tmpStream)

		binData = tmpStream.getvalue()
		self.handle.write(Encoding.EncodeVarint(len(binData)))
		self.handle.write(binData)

	def Sync(self):
		self.handle.write(b"\xee\x07\x00\x00\x00\x00\x00\x00\x00")

	def Reset(self):
		self.handle.write(b"\xff")
		self.ResetDeltaCoding()

	def Finish(self):
		self.handle.write(b"\xfe")

if __name__=="__main__":
	TestDecodeNumber()
	TestEncodeNumber()

