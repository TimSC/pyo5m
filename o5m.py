import struct, datetime, six, calendar, datetime

# ****** o5m utilities ******

def DecodeNumber(stream, signed=False):
	contin = True
	offset = 0
	total = 0
	neg = False
	while contin:
		val = struct.unpack("B", stream.read(1))[0]
		contin = val & 0x80 != 0
		if signed and offset == 0:
			neg = val & 0x1
			val = val >> 1
			total += (val & 0x3f) << offset
			offset += 6
		else:
			total += (val & 0x7f) << offset
			offset += 7
	if neg:
		total = (total * -1) -1
	return total

def TestDecodeNumber():
	assert (DecodeNumber(six.BytesIO(b'\x05')) == 5)
	assert (DecodeNumber(six.BytesIO(b'\x7f')) == 127)
	assert (DecodeNumber(six.BytesIO(b'\xc3\x02')) == 323)
	assert (DecodeNumber(six.BytesIO(b'\x80\x80\x01')) == 16384)
	assert (DecodeNumber(six.BytesIO(b'\x08'), True) == 4)
	assert (DecodeNumber(six.BytesIO(b'\x80\x01'), True) == 64)
	assert (DecodeNumber(six.BytesIO(b'\x03'), True) == -2)
	assert (DecodeNumber(six.BytesIO(b'\x05'), True) == -3)
	assert (DecodeNumber(six.BytesIO(b'\x81\x01'), True) == -65)

def EncodeNumber(num, signed=False):
	out = six.BytesIO()
	num = int(num)

	#Least significant byte
	if signed:
		if num < 0:
			neg = True
			num = (num*-1)-1
		else:
			neg = False
		sixBits = num & 0x3f
		num = num >> 6
		more = num > 0
		out.write(struct.pack("B", (more << 7) + (sixBits << 1) + neg))
	else:
		if num < 0:
			raise ValueError("Value cannot be negative")
		sevenBits = num & 0x7f
		num = num >> 7
		more = num > 0
		out.write(struct.pack("B", (more << 7) + sevenBits))
	
	#Later bytes
	while more:
		sevenBits = num & 0x7f
		num = num >> 7
		more = num > 0
		out.write(struct.pack("B", (more << 7) + sevenBits))
		
	#print map(hex, map(ord, out.getvalue()))
	return out.getvalue()

def TestEncodeNumber():
	assert (EncodeNumber(5) == b'\x05')
	assert (EncodeNumber(127) == b'\x7f')
	assert (EncodeNumber(323) == b'\xc3\x02')
	assert (EncodeNumber(16384) == b'\x80\x80\x01')
	assert (EncodeNumber(4, True) == b'\x08')
	assert (EncodeNumber(64, True) == b'\x80\x01')
	assert (EncodeNumber(-2, True) == b'\x03')
	assert (EncodeNumber(-3, True) == b'\x05')
	assert (EncodeNumber(-65, True) == b'\x81\x01')

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
		self.refTableLengthThreshold = 253

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
		length = DecodeNumber(self.handle)
		unknownDataSet = self.handle.read(length)
		return False

	def DecodeHeader(self):
		length = DecodeNumber(self.handle)
		fileType = self.handle.read(length)
		if self.funcStoreIsDiff != None:
			self.funcStoreIsDiff("o5c2"==fileType)
	
	def DecodeBoundingBox(self):
		length = DecodeNumber(self.handle)
		
		#south-western corner 
		x1 = DecodeNumber(self.handle, True) / 1e7 #lon
		y1 = DecodeNumber(self.handle, True) / 1e7 #lat

		#north-eastern corner
		x2 = DecodeNumber(self.handle, True) / 1e7 #lon
		y2 = DecodeNumber(self.handle, True) / 1e7 #lat

		if self.funcStoreBounds != None:
			self.funcStoreBounds([x1, y1, x2, y2])

	def DecodeSingleString(self, stream):
		outStr = six.BytesIO()
		code = 0x01
		while code != 0x00:
			rawVal = stream.read(1)
			code = struct.unpack("B", rawVal)[0]
			if code != 0x00:
				outStr.write(rawVal)
		return outStr.getvalue()

	def ConsiderAddToStringRefTable(self, firstStr, secondStr):
		#Consider if to add pair to string reference table
		combinedRaw = firstStr+b"\x00"+secondStr+b"\x00"
		self.ConsiderAddBuffToStringRefTable(combinedRaw)

	def ConsiderAddBuffToStringRefTable(self, buff):
		#Consider if to add to string reference table
		if len(buff) < self.refTableLengthThreshold:
			self.stringPairs.append(buff)

			#Make sure it does not grow forever
			if len(self.stringPairs) > 15000:
				self.stringPairs = self.stringPairs[-15000:]

	def ReadStringPair(self, stream):
		ref = DecodeNumber(stream)
		if ref == 0x00:
			#print "new pair"
			firstStr = self.DecodeSingleString(stream)
			secondStr = self.DecodeSingleString(stream)
			self.ConsiderAddToStringRefTable(firstStr, secondStr)
		else:
			#print "ref", ref
			prevPair = six.BytesIO(self.stringPairs[-ref])
			firstStr = self.DecodeSingleString(prevPair)
			secondStr = self.DecodeSingleString(prevPair)
		return firstStr, secondStr

	def DecodeMetaData(self, nodeDataStream):
		#Decode author and time stamp
		version = DecodeNumber(nodeDataStream)
		timestamp = None
		changeset = None
		uid = None
		username = None
		if version != 0:
			deltaTime = DecodeNumber(nodeDataStream, True)
			self.lastTimeStamp += deltaTime
			timestamp = datetime.datetime.utcfromtimestamp(self.lastTimeStamp)
			#print "timestamp", self.lastTimeStamp, deltaTime
			if self.lastTimeStamp != 0:
				deltaChangeSet = DecodeNumber(nodeDataStream, True)
				self.lastChangeSet += deltaChangeSet
				changeset = self.lastChangeSet
				#print "changeset", self.lastChangeSet, deltaChangeSet
				firstString, secondString = self.ReadStringPair(nodeDataStream)

				if len(firstString) > 0:
					uid = DecodeNumber(six.BytesIO(firstString))
					#print "uid", uid
				if len(secondString) > 0:
					username = secondString.decode("utf-8")

		return version, timestamp, changeset, uid, username

	def DecodeNode(self):
		length = DecodeNumber(self.handle)
		nodeData = self.handle.read(length)

		#Decode object ID
		nodeDataStream = six.BytesIO(nodeData)
		deltaId = DecodeNumber(nodeDataStream, True)
		self.lastObjId += deltaId
		objectId = self.lastObjId 
		#print "objectId", objectId

		metaData = self.DecodeMetaData(nodeDataStream)

		self.lastLon += DecodeNumber(nodeDataStream, True)
		self.lastLat += DecodeNumber(nodeDataStream, True)
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
		length = DecodeNumber(self.handle)
		objData = self.handle.read(length)

		#Decode object ID
		objDataStream = six.BytesIO(objData)
		deltaId = DecodeNumber(objDataStream, True)
		self.lastObjId += deltaId
		objectId = self.lastObjId 
		#print "objectId", objectId

		metaData = self.DecodeMetaData(objDataStream)

		refLen = DecodeNumber(objDataStream)
		#print "len ref", refLen

		refStart = objDataStream.tell()
		refs = []
		while objDataStream.tell() < refStart + refLen:
			self.lastRefNode += DecodeNumber(objDataStream, True)
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
		length = DecodeNumber(self.handle)
		objData = self.handle.read(length)

		#Decode object ID
		objDataStream = six.BytesIO(objData)
		deltaId = DecodeNumber(objDataStream, True)
		self.lastObjId += deltaId
		objectId = self.lastObjId 
		#print "objectId", objectId

		metaData = self.DecodeMetaData(objDataStream)

		refLen = DecodeNumber(objDataStream)
		#print "len ref", refLen

		refStart = objDataStream.tell()
		refs = []

		while objDataStream.tell() < refStart + refLen:
			deltaRef = DecodeNumber(objDataStream, True)
			refIndex = DecodeNumber(objDataStream) #Index into reference table
			if refIndex == 0:
				typeAndRoleRaw = self.DecodeSingleString(objDataStream)
				typeAndRole = typeAndRoleRaw.decode("utf-8")
				self.ConsiderAddBuffToStringRefTable(typeAndRoleRaw)
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
		self.refTableLengthThreshold = 253

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
		self.handle.write(EncodeNumber(len(headerData)))
		self.handle.write(headerData)

	def StoreBounds(self, bbox):

		#south-western corner 
		bboxData = []
		bboxData.append(EncodeNumber(round(bbox[0] * 1e7), True)) #lon
		bboxData.append(EncodeNumber(round(bbox[1] * 1e7), True)) #lat

		#north-eastern corner
		bboxData.append(EncodeNumber(round(bbox[2] * 1e7), True)) #lon
		bboxData.append(EncodeNumber(round(bbox[3] * 1e7), True)) #lat
		
		combinedData = b''.join(bboxData)
		self.handle.write(b'\xdb')
		self.handle.write(EncodeNumber(len(combinedData)))
		self.handle.write(combinedData)

	def EncodeMetaData(self, version, timestamp, changeset, uid, username, outStream):
		#Decode author and time stamp
		outStream.write(EncodeNumber(version))
		if version != 0:
			timestamp = calendar.timegm(timestamp.utctimetuple())
			deltaTime = timestamp - self.lastTimeStamp
			outStream.write(EncodeNumber(deltaTime, True))
			self.lastTimeStamp = timestamp
			#print "timestamp", self.lastTimeStamp, deltaTime
			if timestamp != 0:
				#print changeset
				deltaChangeSet = changeset - self.lastChangeSet
				outStream.write(EncodeNumber(deltaChangeSet, True))
				self.lastChangeSet = changeset
				encUid = b""
				if uid is not None:
					encUid = EncodeNumber(uid)
				encUsername = b""
				if username is not None:
					encUsername = username.encode("utf-8")
				self.WriteStringPair(encUid, encUsername, outStream)

	def EncodeSingleString(self, strIn):
		return strIn + b'\x00'

	def WriteStringPair(self, firstString, secondString, tmpStream):
		encodedStrings = firstString + b"\x00" + secondString + b"\x00"
		if len(encodedStrings) < self.refTableLengthThreshold:
			try:
				existIndex = self.stringPairs.index(encodedStrings)
				tmpStream.write(EncodeNumber(len(self.stringPairs) - existIndex))
				return
			except ValueError:
				pass #Key value pair not currently in reference table

		tmpStream.write(b"\x00")
		tmpStream.write(encodedStrings)
		self.ConsiderAddToRefTable(encodedStrings)

	def ConsiderAddToRefTable(self, encodedStrings):
		if len(encodedStrings) < self.refTableLengthThreshold:
			self.stringPairs.append(encodedStrings)

			#Limit size of reference table
			if len(self.stringPairs) > 15000:
				self.stringPairs = self.stringPairs[-15000:]

	def StoreNode(self, objectId, metaData, tags, pos):
		self.handle.write(b"\x10")

		#Object ID
		tmpStream = six.BytesIO()
		deltaId = objectId - self.lastObjId
		tmpStream.write(EncodeNumber(deltaId, True))
		self.lastObjId = objectId

		version, timestamp, changeset, uid, username = metaData
		self.EncodeMetaData(version, timestamp, changeset, uid, username, tmpStream)

		#Position
		lat = round(pos[0] * 1e7)
		deltaLat = lat - self.lastLat
		tmpStream.write(EncodeNumber(deltaLat, True))
		self.lastLat = lat
		lon = round(pos[1] * 1e7)
		deltaLon = lon - self.lastLon
		tmpStream.write(EncodeNumber(deltaLon, True))
		self.lastLon = lon

		for key in tags:
			val = tags[key]
			self.WriteStringPair(key.encode("utf-8"), val.encode("utf-8"), tmpStream)

		binData = tmpStream.getvalue()
		self.handle.write(EncodeNumber(len(binData)))
		self.handle.write(binData)

	def StoreWay(self, objectId, metaData, tags, refs):
		self.handle.write(b"\x11")

		#Object ID
		tmpStream = six.BytesIO()
		deltaId = objectId - self.lastObjId
		tmpStream.write(EncodeNumber(deltaId, True))
		self.lastObjId = objectId

		#Store meta data
		version, timestamp, changeset, uid, username = metaData
		self.EncodeMetaData(version, timestamp, changeset, uid, username, tmpStream)

		#Store nodes
		refStream = six.BytesIO()
		for ref in refs:
			deltaRef = ref - self.lastRefNode
			refStream.write(EncodeNumber(deltaRef, True))
			self.lastRefNode = ref

		encRefs = refStream.getvalue()
		tmpStream.write(EncodeNumber(len(encRefs)))
		tmpStream.write(encRefs)

		#Write tags
		for key in tags:
			val = tags[key]
			self.WriteStringPair(key.encode("utf-8"), val.encode("utf-8"), tmpStream)

		binData = tmpStream.getvalue()
		self.handle.write(EncodeNumber(len(binData)))
		self.handle.write(binData)
		
	def StoreRelation(self, objectId, metaData, tags, refs):
		self.handle.write(b"\x12")

		#Object ID
		tmpStream = six.BytesIO()
		deltaId = objectId - self.lastObjId
		tmpStream.write(EncodeNumber(deltaId, True))
		self.lastObjId = objectId

		#Store meta data
		version, timestamp, changeset, uid, username = metaData
		self.EncodeMetaData(version, timestamp, changeset, uid, username, tmpStream)

		#Store referenced children
		refStream = six.BytesIO()
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

			refStream.write(EncodeNumber(deltaRef, True))

			typeCodeAndRole = (str(typeCode) + role).encode("utf-8")
			try:
				refIndex = self.stringPairs.index(typeCodeAndRole)
				refStream.write(EncodeNumber(len(self.stringPairs) - refIndex))
			except ValueError:
				refStream.write(b'\x00') #String start byte
				refStream.write(self.EncodeSingleString(typeCodeAndRole))
				self.ConsiderAddToRefTable(typeCodeAndRole)

		encRefs = refStream.getvalue()
		tmpStream.write(EncodeNumber(len(encRefs)))
		tmpStream.write(encRefs)

		#Write tags
		for key in tags:
			val = tags[key]
			self.WriteStringPair(key.encode("utf-8"), val.encode("utf-8"), tmpStream)

		binData = tmpStream.getvalue()
		self.handle.write(EncodeNumber(len(binData)))
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

