import OsmData, gzip, o5m

if __name__=="__main__":

	fi = gzip.open("../coastout.o5m.gz", "rb")

	dec = o5m.O5mDecode(fi)
	dec.DecodeHeader()

	eof = False
	while not eof:
		eof = dec.DecodeNext()

	
