import OsmData

if __name__=="__main__":

	fi = open("dahab.o5m", "rb")
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

