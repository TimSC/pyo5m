# pyo5m
o5m openstreetmap format encoder/decoder in python v2 and v3. Includes both stream decoding and static interpretations of data. It also includes a standard osm xml encoder/decoder.

To install in the python distribution:

 python -m pip install .

Example usage:

```python
import gzip
import OsmData

if __name__=="__main__":

	fi = open("o5mtest.o5m", "rb")
	osmData = OsmData.OsmData()
	osmData.LoadFromO5m(fi)
	print ("nodes", len(osmData.nodes))
	print ("ways", len(osmData.ways))
	print ("relations", len(osmData.relations))

	fi2 = open("o5mtest2.o5m", "wb")
	osmData.SaveToO5m(fi2)
	fi2.close()

	print ("Read data back")
	fi3 = open("o5mtest2.o5m", "rb")
	osmData2 = OsmData.OsmData()
	osmData2.LoadFromO5m(fi3)
	print ("nodes", len(osmData2.nodes))
	print ("ways", len(osmData2.ways))
	print ("relations", len(osmData2.relations))

	fi = gzip.open("o5mtest.osm.gz", "rt")
	osmData = OsmData.OsmData()
	osmData.LoadFromOsmXml(fi)
	print ("nodes", len(osmData.nodes))
	print ("ways", len(osmData.ways))
	print ("relations", len(osmData.relations))

```
Streaming osm data during load is also supported.

```python
import OsmData, gzip, o5m

class DataVisitor:

	def StoreNode(self, objectId, metaData, tags, pos):
		print ("node", objectId)

	def StoreWay(self, objectId, metaData, tags, refs):
		print ("way", objectId)

	def StoreRelation(self, objectId, metaData, tags, refs):
		print ("relation", objectId)

	def StoreBounds(self, bbox):
		print ("bbox", bbox)

	def StoreIsDiff(self, isDiff):
		print ("isDiff", isDiff)

if __name__=="__main__":

	fi = gzip.open("o5mtest.o5m.gz", "rb")

	dec = o5m.O5mDecode(fi)

	dataVisitor = DataVisitor()
  
	dec.funcStoreNode = dataVisitor.StoreNode
	dec.funcStoreWay = dataVisitor.StoreWay
	dec.funcStoreRelation = dataVisitor.StoreRelation
	dec.funcStoreBounds = dataVisitor.StoreBounds
	dec.funcStoreIsDiff = dataVisitor.StoreIsDiff

	dec.DecodeHeader()

	eof = False
	while not eof:
		eof = dec.DecodeNext()

```
